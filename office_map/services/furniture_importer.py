"""
Импорт библиотеки мебели из DXF-файлов.

Модуль обрабатывает именованные блоки DXF, извлекает геометрию
LINE и HATCH, определяет цвета элементов и сохраняет результат
в модели FurnitureModel.

Поддерживаются линейные элементы и заливки HATCH
с полилинейными контурами.
"""

from pathlib import Path

import ezdxf
from ezdxf import bbox
from ezdxf.colors import int2rgb, aci2rgb

from django.db import transaction

from office_map.models import FurnitureModel


def get_dxf_color(entity, doc):
    """
    Определяет цвет DXF-элемента и возвращает его в формате #RRGGBB.

    Сначала проверяет наличие явно заданного true_color.
    Если он отсутствует, использует индекс цвета ACI.

    Для цветов BYLAYER и BYBLOCK (индексы 256 и 0)
    получает цвет соответствующего слоя.
    """

    # Проверяем, задан ли для элемента цвет напрямую в формате RGB.
    true_color = entity.dxf.get('true_color')

    if true_color is not None:
        rgb = int2rgb(true_color)
        return '#{:02X}{:02X}{:02X}'.format(*rgb)

    # Если RGB-цвет не задан, используем индекс цвета ACI.
    color_index = entity.dxf.get('color', 256)

    # Для BYLAYER и BYBLOCK используем цвет слоя элемента.
    if color_index in (0, 256):
        layer_name = entity.dxf.get('layer', '0')
        layer = doc.layers.get(layer_name)
        color_index = layer.dxf.get('color', 7)

    # Преобразуем индекс ACI в RGB.
    rgb = aci2rgb(abs(color_index))

    return '#{:02X}{:02X}{:02X}'.format(
        rgb.r,
        rgb.g,
        rgb.b,
    )


def extract_hatch_paths(entity):
    """
    Извлекает полилинейные контуры из DXF-элемента HATCH.

    Обрабатывает PolylinePath, преобразуя координаты вершин
    в список точек с числовыми значениями X и Y.

    Контуры, которые не содержат подходящих вершин или имеют
    некорректные координаты, пропускаются.

    Возвращает:
        hatch_paths — список обработанных контуров;
        skipped_paths — количество пропущенных контуров.

    EdgePath с дугами и отдельными рёбрами пока не поддерживается.
    """

    # Список успешно обработанных контуров и счётчик пропущенных.
    hatch_paths = []
    skipped_paths = 0

    # Перебираем границы заливки HATCH.
    for boundary in entity.paths:
        vertices = getattr(boundary, 'vertices', None)

        if not vertices:
            skipped_paths += 1
            continue

        # Подготавливаем список координат текущего контура.
        points = []

        # Получаем вершины полилинейного контура, если они доступны.
        for vertex in vertices:
            # Преобразуем координаты вершины в числа с плавающей точкой.
            try:
                x = float(vertex[0])
                y = float(vertex[1])
            except (TypeError, ValueError, IndexError):
                points = []
                break

            points.append({
                'x': x,
                'y': y,
            })

        # Для контура нужны минимум три корректные точки.
        if len(points) >= 3:
            hatch_paths.append(points)
        else:
            skipped_paths += 1

    return hatch_paths, skipped_paths


@transaction.atomic
def import_furniture_library(file_path):
    """
    Импортирует именованные блоки мебели из DXF-файла в базу данных.

    Для каждого блока:
    - определяет габариты по геометрии;
    - извлекает LINE и HATCH;
    - сохраняет координаты, цвета и названия слоёв;
    - создаёт или обновляет запись FurnitureModel.

    Анонимные и системные блоки, пустые блоки и блоки
    без поддерживаемой геометрии пропускаются.

    Импорт выполняется в рамках одной транзакции.
    При возникновении ошибки изменения базы данных откатываются.

    Возвращает список созданных или обновлённых объектов мебели.
    Если подходящие блоки не найдены, вызывает ValueError.
    """

    # Преобразуем путь к DXF-файлу в объект Path.
    file_path = Path(file_path)

    # Загружаем DXF-документ для обработки его блоков и элементов.
    doc = ezdxf.readfile(file_path)

    imported = []

    # Общая статистика импорта геометрических элементов.
    total_lines = 0
    total_hatches = 0
    total_skipped_hatch_paths = 0

    # Перебираем все блоки DXF-документа.
    for block in doc.blocks:
        block_name = block.name

        # Пропускаем анонимные и системные блоки DXF.
        if block_name.startswith('*'):
            continue

        # Определяем габариты блока по его геометрии.
        extents = bbox.extents(block)

        # Пропускаем блоки, для которых не удалось определить габариты.
        if not extents.has_data:
            continue

        # Сохраняем границы блока для последующего расчёта размеров мебели.
        min_x = extents.extmin.x
        min_y = extents.extmin.y
        max_x = extents.extmax.x
        max_y = extents.extmax.y

        # Здесь будет храниться геометрия всех поддерживаемых элементов блока.
        geometry = []

        # Счётчики LINE и HATCH для текущего блока.
        block_lines = 0
        block_hatches = 0

        # Обрабатываем элементы геометрии внутри текущего блока.
        for entity in block:
            # Определяем тип элемента и его цвет.
            entity_type = entity.dxftype()
            color = get_dxf_color(entity, doc)

            # Извлекаем координаты и свойства линейных элементов.
            if entity_type == 'LINE':
                start = entity.dxf.start
                end = entity.dxf.end

                geometry.append({
                    'type': 'line',
                    'x1': float(start.x),
                    'y1': float(start.y),
                    'x2': float(end.x),
                    'y2': float(end.y),
                    'color': color,
                    'layer': entity.dxf.layer,
                })

                block_lines += 1

            # Извлекаем полилинейные контуры заливки HATCH.
            elif entity_type == 'HATCH':
                hatch_paths, skipped = extract_hatch_paths(entity)

                total_skipped_hatch_paths += skipped

                # Если поддерживаемые контуры не найдены, пропускаем заливку.
                if not hatch_paths:
                    print(
                        f'Внимание: HATCH в блоке {block_name} '
                        f'не содержит поддерживаемых полилинейных контуров'
                    )
                    continue

                # Сохраняем контуры заливки вместе с цветом и правилом заполнения.
                geometry.append({
                    'type': 'hatch',
                    'paths': hatch_paths,
                    'color': color,
                    'layer': entity.dxf.layer,
                    'fill_rule': 'evenodd',
                })

                block_hatches += 1

        # Не сохраняем блоки, в которых не удалось извлечь геометрию.
        if not geometry:
            print(f'Пропущен пустой блок: {block_name}')
            continue

        # Создаём новую запись мебели или обновляем существующую по имени блока.
        furniture, created = FurnitureModel.objects.update_or_create(
            block_name=block_name,
            defaults={
                'name': block_name,
                'width_mm': max_x - min_x,
                'height_mm': max_y - min_y,
                'geometry': geometry,
                'is_active': True,
            },
        )

        # Добавляем успешно обработанную мебель в результат импорта.
        imported.append(furniture)

        # Обновляем общую статистику импортированных элементов.
        total_lines += block_lines
        total_hatches += block_hatches

        print(
            f'{"Создана" if created else "Обновлена"}: '
            f'{block_name} | '
            f'LINE: {block_lines} | '
            f'HATCH: {block_hatches} | '
            f'Всего элементов: {len(geometry)}'
        )

    # Если ни одного подходящего блока не найдено, завершаем импорт с ошибкой.
    if not imported:
        raise ValueError(
            'В DXF не найдено подходящих блоков мебели'
        )

    # Выводим общую статистику завершённого импорта.
    print()
    print('Импорт завершён')
    print(f'Блоков: {len(imported)}')
    print(f'LINE: {total_lines}')
    print(f'HATCH: {total_hatches}')
    print(
        'Пропущено контуров HATCH: '
        f'{total_skipped_hatch_paths}'
    )

    # Возвращаем список созданных или обновлённых объектов мебели.
    return imported
