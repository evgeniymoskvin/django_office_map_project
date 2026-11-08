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
import math

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
    Извлекает контуры HATCH и преобразует дуговые сегменты
    полилинейных границ в последовательность точек.

    Параметр bulge определяет дугу между текущей и следующей
    вершинами. Для плавного отображения дуга разбивается
    на сегменты с угловым шагом не более 10 градусов.
    """
    hatch_paths = []
    skipped_paths = 0

    for boundary in entity.paths:
        vertices = getattr(boundary, 'vertices', None)

        if not vertices:
            skipped_paths += 1
            continue

        points = []

        # Перебираем вершины и соединяющие их сегменты.
        vertex_count = len(vertices)
        is_closed = bool(getattr(boundary, 'is_closed', False))

        segment_count = (
            vertex_count if is_closed else vertex_count - 1
        )

        try:
            for i in range(segment_count):
                current = vertices[i]
                next_vertex = vertices[(i + 1) % vertex_count]

                x1 = float(current[0])
                y1 = float(current[1])
                x2 = float(next_vertex[0])
                y2 = float(next_vertex[1])

                # Bulge хранится третьим значением вершины.
                bulge = (
                    float(current[2])
                    if len(current) > 2
                    else 0.0
                )

                # Добавляем начальную точку сегмента.
                if not points:
                    points.append({'x': x1, 'y': y1})

                # Прямой сегмент — достаточно конечной точки.
                if abs(bulge) < 1e-9:
                    points.append({'x': x2, 'y': y2})
                    continue

                # Вычисляем параметры дуги по bulge.
                dx = x2 - x1
                dy = y2 - y1
                chord = math.hypot(dx, dy)

                if chord < 1e-9:
                    continue

                angle = 4.0 * math.atan(bulge)

                # Центр окружности, проходящей через концы дуги.
                offset = chord * (1.0 - bulge ** 2) / (4.0 * bulge)

                center_x = (x1 + x2) / 2.0 - dy / chord * offset
                center_y = (y1 + y2) / 2.0 + dx / chord * offset

                radius = math.hypot(
                    x1 - center_x,
                    y1 - center_y,
                )

                start_angle = math.atan2(
                    y1 - center_y,
                    x1 - center_x,
                )

                # Количество отрезков: не более 10 градусов на каждый.
                steps = max(
                    1,
                    math.ceil(abs(angle) / math.radians(10)),
                )

                # Добавляем промежуточные точки дуги.
                for step in range(1, steps + 1):
                    current_angle = (
                            start_angle + angle * step / steps
                    )

                    points.append({
                        'x': center_x + radius * math.cos(current_angle),
                        'y': center_y + radius * math.sin(current_angle),
                    })

        except (TypeError, ValueError, IndexError, OverflowError):
            points = []

        # Для замкнутого контура нужно минимум три точки.
        if len(points) >= 3:
            hatch_paths.append(points)
        else:
            skipped_paths += 1

    return hatch_paths, skipped_paths


def extract_polyline_segments(entity, angle_step=10):
    """
    Преобразует LWPOLYLINE в последовательность прямых сегментов.

    Учитывает bulge, благодаря чему дуговые участки превращаются
    в набор коротких отрезков.
    """
    vertices = entity.get_points('xyb')

    if len(vertices) < 2:
        return []

    segments = []
    vertex_count = len(vertices)

    segment_count = (
        vertex_count if entity.closed else vertex_count - 1
    )

    for i in range(segment_count):
        current = vertices[i]
        next_vertex = vertices[(i + 1) % vertex_count]

        x1, y1, bulge = map(float, current)
        x2, y2 = float(next_vertex[0]), float(next_vertex[1])

        dx = x2 - x1
        dy = y2 - y1

        # Обычный прямой сегмент.
        if abs(bulge) < 1e-9:
            segments.append((x1, y1, x2, y2))
            continue

        chord = math.hypot(dx, dy)

        if chord < 1e-9:
            continue

        # Вычисляем параметры дуги.
        angle = 4.0 * math.atan(bulge)
        offset = chord * (1.0 - bulge ** 2) / (4.0 * bulge)

        center_x = (x1 + x2) / 2.0 - dy / chord * offset
        center_y = (y1 + y2) / 2.0 + dx / chord * offset

        radius = math.hypot(
            x1 - center_x,
            y1 - center_y,
        )

        start_angle = math.atan2(
            y1 - center_y,
            x1 - center_x,
        )

        steps = max(
            1,
            math.ceil(abs(angle) / math.radians(angle_step)),
        )

        points = [(x1, y1)]

        for step in range(1, steps + 1):
            current_angle = start_angle + angle * step / steps

            points.append((
                center_x + radius * math.cos(current_angle),
                center_y + radius * math.sin(current_angle),
            ))

        # Каждую пару соседних точек сохраняем как отдельную линию.
        for j in range(len(points) - 1):
            start = points[j]
            end = points[j + 1]

            segments.append((
                start[0],
                start[1],
                end[0],
                end[1],
            ))

    return segments


def extract_arc_segments(entity, angle_step=10):
    """
    Преобразует DXF-дугу ARC в последовательность прямых сегментов.

    DXF хранит дугу через центр, радиус, начальный и конечный углы.
    Углы задаются в градусах.
    """
    center = entity.dxf.center
    radius = float(entity.dxf.radius)

    start_angle = math.radians(float(entity.dxf.start_angle))
    end_angle = math.radians(float(entity.dxf.end_angle))

    # DXF ARC проходит против часовой стрелки.
    sweep = (end_angle - start_angle) % (2 * math.pi)

    if radius <= 0 or sweep < 1e-9:
        return []

    steps = max(
        1,
        math.ceil(math.degrees(sweep) / angle_step),
    )

    points = []

    for i in range(steps + 1):
        angle = start_angle + sweep * i / steps

        points.append((
            float(center.x) + radius * math.cos(angle),
            float(center.y) + radius * math.sin(angle),
        ))

    segments = []

    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]

        segments.append((x1, y1, x2, y2))

    return segments


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
            elif entity_type == 'ARC':
                segments = extract_arc_segments(entity)

                for x1, y1, x2, y2 in segments:
                    geometry.append({
                        'type': 'line',
                        'x1': x1,
                        'y1': y1,
                        'x2': x2,
                        'y2': y2,
                        'color': color,
                        'layer': entity.dxf.layer,
                    })

                block_lines += len(segments)

            elif entity_type == 'LWPOLYLINE':
                segments = extract_polyline_segments(entity)

                for x1, y1, x2, y2 in segments:
                    geometry.append({
                        'type': 'line',
                        'x1': x1,
                        'y1': y1,
                        'x2': x2,
                        'y2': y2,
                        'color': color,
                        'layer': entity.dxf.layer,
                    })

                block_lines += len(segments)

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
