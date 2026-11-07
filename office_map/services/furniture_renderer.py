"""
Формирование SVG-изображений мебели для плана этажа и каталога.

Модуль преобразует сохранённую геометрию мебели в SVG-элементы,
учитывает координаты размещения и угол поворота, сохраняет цвета
и заливки DXF-элементов.

Поддерживает:
- отрисовку мебели на плане этажа;
- генерацию SVG отдельного размещения;
- создание миниатюр мебели для каталога.
"""

import math
import xml.etree.ElementTree as ET

from .dxf_converter import dxf_to_svg_coordinates


SVG_NS = 'http://www.w3.org/2000/svg'


def _svg_tag(name):
    """
    Возвращает имя SVG-тега с учётом пространства имён SVG.
    Используется при создании элементов XML-структуры SVG.
    """
    return f'{{{SVG_NS}}}{name}'


def _normalize_svg_color(color, fallback='#343a40'):
    """
    Проверяет цвет элемента и возвращает допустимое значение SVG.
    Если цвет задан строкой в формате HEX, возвращает его без изменений.
    В остальных случаях использует переданный цвет по умолчанию.
    """
    if isinstance(color, str) and color.startswith('#'):
        return color

    return fallback


def _transform_point(x, y, placement):
    """
    Преобразует локальные координаты точки с учётом размещения мебели.

    Поворачивает точку на угол placement.rotation вокруг начала
    координат, затем переносит её в позицию placement.x и placement.y.

    Возвращает координаты точки в системе координат плана.
    """

    # Переводим угол поворота из градусов в радианы.
    angle = math.radians(placement.rotation)

    # Вычисляем значения для матрицы двумерного поворота.
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)

    # Поворачиваем исходную точку относительно начала координат.
    rotated_x = x * cos_a - y * sin_a
    rotated_y = x * sin_a + y * cos_a

    # Переносим повернутую точку в координаты размещения мебели.
    return (
        placement.x + rotated_x,
        placement.y + rotated_y,
    )


def _build_furniture_group(plan, placement):
    """
    Создаёт SVG-группу для одного размещения мебели на плане.

    Получает геометрию мебели, преобразует координаты её элементов
    с учётом положения и поворота, затем формирует SVG-контуры
    заливок HATCH и линий LINE.

    В группу добавляются атрибуты data-*, необходимые JavaScript
    для идентификации объекта и управления его положением.

    Если геометрия отсутствует или не содержит поддерживаемых
    элементов, возвращает None.
    """
    # Получаем объект мебели, связанный с текущим размещением.
    furniture = placement.furniture

    # Преобразуем координаты точки размещения из DXF в SVG.
    anchor_x, anchor_y = dxf_to_svg_coordinates(
        plan,
        placement.x,
        placement.y,
    )

    # Создаём SVG-группу и сохраняем идентификаторы,
    # координаты и угол поворота для дальнейшей работы JavaScript.
    group = ET.Element(
        _svg_tag('g'),
        {
            'class': 'furniture-debug',
            'data-placement-id': str(placement.id),
            'data-furniture-id': str(furniture.id),
            'data-x': str(placement.x),
            'data-y': str(placement.y),
            'data-base-x': str(placement.x),
            'data-base-y': str(placement.y),
            'data-rotation': str(placement.rotation),
            'data-anchor-x': str(anchor_x),
            'data-anchor-y': str(anchor_y),
            'pointer-events': 'visiblePainted',
        },
    )

    # Создаём отдельную группу для геометрических элементов мебели.
    geometry_group = ET.SubElement(
        group,
        _svg_tag('g'),
        {'class': 'furniture-geometry'},
    )

    geometry = furniture.geometry

    # Проверяем, что сохранённая геометрия имеет ожидаемый формат.
    if not isinstance(geometry, list):
        return None

    # Сначала отрисовываем заливки HATCH, затем линии LINE,
    # чтобы контуры заливок не перекрывали линейные элементы.
    ordered_geometry = sorted(
        geometry,
        key=lambda item: 0 if item.get('type') == 'hatch' else 1,
    )

    # Отслеживаем, удалось ли добавить хотя бы один элемент геометрии.
    has_geometry = False

    # Последовательно формируем SVG-элементы мебели.
    for item in ordered_geometry:
        item_type = item.get('type', 'line')
        color = _normalize_svg_color(item.get('color'))

        # Обрабатываем заливки HATCH с полилинейными контурами.
        if item_type == 'hatch':
            # Здесь собираются SVG-контуры всех границ текущей заливки.
            path_parts = []

            # Обрабатываем каждый контур заливки отдельно.
            for boundary in item.get('paths', []):
                # Для замкнутого контура требуется минимум три точки.
                if len(boundary) < 3:
                    continue

                points = []

                # Преобразуем локальные координаты вершин
                # с учётом поворота и положения мебели.
                for point in boundary:
                    world_x, world_y = _transform_point(
                        point['x'],
                        point['y'],
                        placement,
                    )

                    svg_x, svg_y = dxf_to_svg_coordinates(
                        plan,
                        world_x,
                        world_y,
                    )

                    points.append((svg_x, svg_y))

                if not points:
                    continue

                path = (
                    f'M {points[0][0]:.3f},{points[0][1]:.3f} '
                    + ' '.join(
                        f'L {x:.3f},{y:.3f}'
                        for x, y in points[1:]
                    )
                    + ' Z'
                )

                path_parts.append(path)

            # Если найдены корректные контуры, создаём SVG-элемент path.
            if path_parts:
                ET.SubElement(
                    geometry_group,
                    _svg_tag('path'),
                    {
                        'class': 'furniture-item',
                        'd': ' '.join(path_parts),
                        'fill': color,
                        'stroke': 'none',
                        'fill-rule': item.get(
                            'fill_rule',
                            'evenodd',
                        ),
                        'pointer-events': 'visiblePainted',
                    },
                )

                # Отмечаем, что в группу добавлена геометрия.
                has_geometry = True

        # Обрабатываем линейные элементы мебели.
        elif item_type == 'line':
            # Поддержка нового и старого формата geometry.
            try:
                # Получаем координаты начала и конца линии.
                coordinates = (
                    (float(item['x1']), float(item['y1'])),
                    (float(item['x2']), float(item['y2'])),
                )
            except (KeyError, TypeError, ValueError):
                continue

            # Подготавливаем преобразованные координаты концов линии.
            points = []

            for x, y in coordinates:
                world_x, world_y = _transform_point(
                    x,
                    y,
                    placement,
                )

                # Создаём SVG-линию с сохранением цвета и параметров обводки.
                svg_x, svg_y = dxf_to_svg_coordinates(
                    plan,
                    world_x,
                    world_y,
                )

                points.append((svg_x, svg_y))

            ET.SubElement(
                geometry_group,
                _svg_tag('path'),
                {
                    'class': 'furniture-item',
                    'pointer-events': 'visiblePainted',
                    'd': (
                        f'M {points[0][0]:.3f},{points[0][1]:.3f} '
                        f'L {points[1][0]:.3f},{points[1][1]:.3f}'
                    ),
                    'fill': 'none',
                    'stroke': color,
                    'stroke-width': '250',
                    'stroke-linecap': 'round',
                    'stroke-linejoin': 'round',
                },
            )

            has_geometry = True
    # Возвращаем группу только в том случае, если в ней есть геометрия.
    return group if has_geometry else None


def generate_furniture_placement_svg(plan, placement):
    """
    Генерирует SVG одного размещения мебели для динамической вставки.

    Создаёт SVG-группу мебели с учётом её положения, поворота,
    геометрии и цветов.

    Если для размещения не удалось сформировать геометрию,
    возвращает пустую строку.
    """
    # Регистрируем пространство имён SVG для корректной сериализации XML.
    ET.register_namespace('', SVG_NS)
    # Формируем SVG-группу текущего размещения мебели.
    group = _build_furniture_group(plan, placement)
    # Если геометрия отсутствует, возвращаем пустой результат.
    if group is None:
        return ''
    # Преобразуем SVG-элемент в строку для передачи в шаблон или JavaScript.
    return ET.tostring(group, encoding='unicode')


def generate_furniture_svg(plan):
    """
    Генерирует общий SVG-слой мебели для указанного плана этажа.

    Создаёт корневой SVG-элемент с системой координат плана,
    получает активные размещения активной мебели и добавляет
    для каждого размещения отдельную SVG-группу.

    Возвращает готовый SVG в виде строки.
    """
    # Регистрируем пространство имён SVG.
    ET.register_namespace('', SVG_NS)
    # Получаем границы отображения и систему координат плана.
    view_box = plan.coordinate_system['viewBox']
    cs = plan.coordinate_system
    # Создаём корневой SVG-элемент и сохраняем параметры плана.
    svg = ET.Element(
        _svg_tag('svg'),
        {
            'viewBox': ' '.join(map(str, view_box)),
            'preserveAspectRatio': 'xMidYMid meet',
            'class': 'furniture-layer',
            'data-min-x': str(cs['min_x']),
            'data-min-y': str(cs['min_y']),
            'data-max-x': str(cs['max_x']),
            'data-max-y': str(cs['max_y']),
        },
    )

    # Получаем активные размещения мебели и предварительно
    # загружаем связанные объекты мебели.
    placements = (
        plan.furniture_placements
        .filter(
            is_active=True,
            furniture__is_active=True,
        )
        .select_related('furniture')
    )

    # Формируем SVG-группу для каждого размещения.
    for placement in placements:
        group = _build_furniture_group(plan, placement)
        # Добавляем только группы, содержащие корректную геометрию.
        if group is not None:
            svg.append(group)
    # Сериализуем весь слой мебели в SVG-строку.
    return ET.tostring(svg, encoding='unicode')


def generate_furniture_preview_svg(furniture):
    """
    Генерирует SVG-миниатюру мебели для отображения в каталоге.

    Определяет габариты геометрии, масштабирует её до области
    предпросмотра и центрирует относительно SVG-холста.

    Поддерживает заливки HATCH и линии LINE с сохранением цветов.

    Если геометрия отсутствует или не содержит корректных точек,
    возвращает пустую строку.
    """
    # Регистрируем пространство имён SVG.
    ET.register_namespace('', SVG_NS)
    # Получаем сохранённую геометрию объекта мебели.
    geometry = furniture.geometry
    # Проверяем наличие геометрии для построения миниатюры.
    if not isinstance(geometry, list) or not geometry:
        return ''
    # Создаём SVG-холст с квадратной областью предпросмотра.
    svg = ET.Element(
        _svg_tag('svg'),
        {
            'viewBox': '0 0 1000 1000',
            'preserveAspectRatio': 'xMidYMid meet',
        },
    )

    # Определяем границы всех элементов.
    points = []
    # Собираем координаты всех точек, чтобы определить габариты мебели.
    for item in geometry:
        if item.get('type') == 'hatch':
            for boundary in item.get('paths', []):
                points.extend(
                    (p['x'], -p['y'])
                    for p in boundary
                )

        else:
            try:
                points.extend([
                    (float(item['x1']), -float(item['y1'])),
                    (float(item['x2']), -float(item['y2'])),
                ])
            except (KeyError, TypeError, ValueError):
                continue
    # Если корректных точек нет, миниатюру построить невозможно.
    if not points:
        return ''
    # Определяем минимальные и максимальные координаты геометрии.
    min_x = min(p[0] for p in points)
    max_x = max(p[0] for p in points)
    min_y = min(p[1] for p in points)
    max_y = max(p[1] for p in points)
    # Рассчитываем размеры объекта, исключая нулевые значения.
    width = max(max_x - min_x, 1)
    height = max(max_y - min_y, 1)
    # Подбираем единый масштаб, чтобы мебель поместилась в область предпросмотра.
    scale = 900 / max(width, height)
    # Рассчитываем смещение для центрирования объекта на холсте.
    offset_x = 500 - (min_x + max_x) * scale / 2
    offset_y = 500 - (min_y + max_y) * scale / 2

    # Преобразуем координаты DXF в координаты миниатюры SVG.
    # Ось Y инвертируется, поскольку в SVG она направлена вниз.
    def preview_point(x, y):
        return (
            x * scale + offset_x,
            -y * scale + offset_y,
        )

    # Сортируем элементы: сначала заливки, затем линии.
    ordered_geometry = sorted(
        geometry,
        key=lambda item: 0 if item.get('type') == 'hatch' else 1,
    )

    # Строим SVG-представление каждого элемента мебели.
    for item in ordered_geometry:
        item_type = item.get('type', 'line')
        color = _normalize_svg_color(item.get('color'))
        # Формируем замкнутые контуры заливки HATCH.
        if item_type == 'hatch':
            paths = []

            for boundary in item.get('paths', []):
                if len(boundary) < 3:
                    continue
                # Преобразуем вершины контура в координаты миниатюры.
                converted = [
                    preview_point(p['x'], p['y'])
                    for p in boundary
                ]

                path = (
                    f'M {converted[0][0]:.3f},{converted[0][1]:.3f} '
                    + ' '.join(
                        f'L {x:.3f},{y:.3f}'
                        for x, y in converted[1:]
                    )
                    + ' Z'
                )

                paths.append(path)
            # Добавляем заливку, если удалось сформировать хотя бы один контур.
            if paths:
                ET.SubElement(
                    svg,
                    _svg_tag('path'),
                    {
                        'd': ' '.join(paths),
                        'fill': color,
                        'stroke': 'none',
                        'fill-rule': 'evenodd',
                    },
                )
        # Формируем линейные элементы мебели.
        elif item_type == 'line':
            try:
                p1 = preview_point(
                    float(item['x1']),
                    float(item['y1']),
                )
                p2 = preview_point(
                    float(item['x2']),
                    float(item['y2']),
                )
            except (KeyError, TypeError, ValueError):
                continue
            # Добавляем линию с сохранением её исходного цвета.
            ET.SubElement(
                svg,
                _svg_tag('path'),
                {
                    'd': (
                        f'M {p1[0]:.3f},{p1[1]:.3f} '
                        f'L {p2[0]:.3f},{p2[1]:.3f}'
                    ),
                    'fill': 'none',
                    'stroke': color,
                    'stroke-width': '2',
                    'stroke-linecap': 'round',
                    'stroke-linejoin': 'round',
                },
            )
    # Возвращаем готовую SVG-миниатюру в виде строки.
    return ET.tostring(svg, encoding='unicode')