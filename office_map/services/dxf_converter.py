from pathlib import Path
import re
import ezdxf
from django.core.files.base import ContentFile
from ezdxf.addons.drawing import Frontend
from ezdxf.addons.drawing.svg import SVGBackend
from ezdxf.addons.drawing.layout import Page, Settings
from ezdxf.addons.drawing.properties import RenderContext
from ezdxf import bbox
from django.db import transaction
from office_map.models import RoomContourModel
import xml.etree.ElementTree as ET


def inspect_dxf(file_path):
    """
    Диагностическая функция для анализа исходного DXF-файла.

    Выводит в консоль:
    - версию формата DXF;
    - общее количество объектов;
    - список слоёв и их видимость;
    - количество объектов каждого типа;
    - количество объектов на каждом слое.

    Используется при изучении исходных чертежей
    и проверке их структуры перед импортом.
    Возвращает загруженный DXF-документ.
    """

    doc = ezdxf.readfile(file_path)
    msp = doc.modelspace()

    print('\n=== DXF INFO ===')
    print('DXF version:', doc.dxfversion)
    print('Entities:', len(msp))

    print('\n=== LAYERS ===')
    for layer in doc.layers:
        print(
            f'{layer.dxf.name}: '
            f'color={layer.dxf.color}, '
            f'visible={not layer.is_off()}'
        )

    print('\n=== ENTITY TYPES ===')
    entity_types = {}

    for entity in msp:
        entity_type = entity.dxftype()
        entity_types[entity_type] = entity_types.get(entity_type, 0) + 1

    for entity_type, count in sorted(entity_types.items()):
        print(f'{entity_type}: {count}')

    print('\n=== ENTITIES BY LAYER ===')
    layer_entities = {}

    for entity in msp:
        layer = entity.dxf.layer
        layer_entities[layer] = layer_entities.get(layer, 0) + 1

    for layer, count in sorted(layer_entities.items()):
        print(f'{layer}: {count}')

    return doc


def inspect_room_geometry(doc):
    """
    Выводит геометрию объектов слоя 02_ROOMS.

    Показывает тип объекта, его уникальный DXF Handle,
    координаты вершин и признак замкнутости полилиний.

    Используется для диагностики контуров помещений
    в исходном чертеже.
    """
    msp = doc.modelspace()

    print('\n=== ROOM GEOMETRY ===')

    for entity in msp.query('*[layer=="02_ROOMS"]'):
        print('\nType:', entity.dxftype())
        print('Handle:', entity.dxf.handle)

        if entity.dxftype() == 'LWPOLYLINE':
            print('Closed:', entity.closed)
            print('Points:', len(entity))
            print('Coordinates:')

            for point in entity.get_points():
                print(f'  X={point[0]}, Y={point[1]}')

        elif entity.dxftype() == 'LINE':
            print('Start:', entity.dxf.start)
            print('End:', entity.dxf.end)


def inspect_room_bounds(doc):
    """
    Выводит габариты объектов слоя 02_ROOMS.

    Для каждого объекта рассчитывает минимальные и максимальные
    координаты X/Y, ширину, высоту и площадь ограничивающего
    прямоугольника (bounding box).

    Используется для проверки размеров контуров.
    Это не точная площадь помещения, а площадь прямоугольника,
    описанного вокруг объекта.
    """
    msp = doc.modelspace()

    print('\n=== ROOM BOUNDS ===')

    for entity in msp.query('*[layer=="02_ROOMS"]'):
        points = [
            (point[0], point[1])
            for point in entity.get_points()
        ]

        is_closed = (
                len(points) >= 3
                and points[0] == points[-1]
        )

        xs = [point[0] for point in points]
        ys = [point[1] for point in points]

        width = max(xs) - min(xs)
        height = max(ys) - min(ys)

        print(f'\nHandle: {entity.dxf.handle}')
        print(f'Closed geometrically: {is_closed}')
        print(f'Width: {width:.2f}')
        print(f'Height: {height:.2f}')
        print(f'Area bounds: {width * height:.2f}')


def convert_dxf_to_svg(plan):
    """
    Преобразует исходный DXF-чертёж этажа в SVG.

    Основные этапы:
    1. Загружает исходный DXF-файл.
    2. Определяет границы всей геометрии чертежа.
    3. Формирует SVG с помощью библиотеки ezdxf.
    4. Получает viewBox готового SVG.
    5. Сохраняет систему координат исходного DXF в плане.
    6. Выполняет необходимую корректировку цветов линий.
    7. Сохраняет SVG в поле svg_file модели плана.

    Система координат сохраняется отдельно, поскольку
    в дальнейшем она используется для преобразования
    координат сотрудников, мебели и контуров помещений.

    Возвращает сохранённый SVG-файл.
    """
    dxf_path = Path(plan.source_file.path)
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    extents = bbox.extents(msp)

    min_x = extents.extmin.x
    min_y = extents.extmin.y
    max_x = extents.extmax.x
    max_y = extents.extmax.y

    source_width = max_x - min_x
    source_height = max_y - min_y

    if source_width <= 0 or source_height <= 0:
        raise ValueError('Некорректные границы чертежа')

    if not extents.has_data:
        raise ValueError('В DXF не найдена геометрия')

    page = Page(width=1200, height=1200)

    settings = Settings(
        fit_page=True,
        scale=1.0,
        output_layers=True,
    )

    backend = SVGBackend()
    context = RenderContext(doc)
    frontend = Frontend(context, backend)

    frontend.draw_layout(msp, finalize=True)

    svg_content = backend.get_string(page, settings=settings)
    print(svg_content[:500])

    svg_content = re.sub(
        r'<rect\s+fill="#212830"[^>]*/>',
        '',
        svg_content,
    )

    viewbox_match = re.search(
        r'viewBox="([^"]+)"',
        svg_content,
    )

    if not viewbox_match:
        raise ValueError('В SVG не найден viewBox')

    viewbox = [float(value) for value in viewbox_match.group(1).split()]

    print('DXF extents:')
    print(min_x, min_y, max_x, max_y)

    print('SVG viewBox:')
    print(viewbox)

    contour = plan.room_contours.filter(is_active=True).first()

    if contour:
        print('DXF contour first point:')
        print(contour.geometry['points'][0])

    # Сохраняем связь между координатами исходного DXF
    # и системой координат SVG.
    # Эти параметры необходимы для правильного размещения
    # сотрудников, мебели и контуров поверх изображения плана.

    plan.coordinate_system = {
        'min_x': min_x,
        'min_y': min_y,
        'max_x': max_x,
        'max_y': max_y,
        'viewBox': viewbox,
        'source_units': 'mm',
        'y_axis_inverted': True,
    }
    plan.save(update_fields=['coordinate_system'])

    # Приводим отдельные цвета линий к единому цвету оформления карты.

    for color in ('#ffffff', '#003fff', '#ffff7f'):
        svg_content = svg_content.replace(
            f'stroke: {color};',
            'stroke: #343a40;',
        )

    plan.svg_file.save(
        f'{plan.id}.svg',
        ContentFile(svg_content.encode('utf-8')),
        save=True,
    )

    print('SVG сохранён:', plan.svg_file.name)
    return plan.svg_file


def extract_room_contours(plan):
    """
    Извлекает геометрию помещений из слоя 02_ROOMS исходного DXF.

    Обрабатывает замкнутые и незамкнутые объекты LWPOLYLINE.
    Для каждого объекта сохраняет:
    - DXF Handle — уникальный идентификатор объекта в чертеже;
    - тип геометрии;
    - признак замкнутости;
    - координаты всех вершин.

    Координаты остаются в исходной системе DXF (миллиметры).
    Преобразование в SVG-координаты выполняется отдельно
    при формировании слоя контуров.

    Возвращает список найденных контуров.
    """
    doc = ezdxf.readfile(plan.source_file.path)
    msp = doc.modelspace()

    contours = []

    for entity in msp:
        if entity.dxf.layer != '02_ROOMS':
            continue

        if entity.dxftype() == 'LWPOLYLINE':
            points = [
                {'x': point[0], 'y': point[1]}
                for point in entity.get_points('xy')
            ]

            contours.append({
                'handle': entity.dxf.handle,
                'type': 'LWPOLYLINE',
                'closed': entity.closed,
                'points': points,
            })

    return contours


@transaction.atomic
def import_room_contours(plan):
    """
    Импортирует контуры помещений из исходного DXF в базу данных.

    Сначала получает геометрию объектов слоя 02_ROOMS
    через extract_room_contours().

    Для каждого контура выполняет update_or_create():
    - если контур с таким DXF Handle уже существует на плане,
      обновляет его геометрию;
    - если контура ещё нет, создаёт новую запись.

    После импорта удаляет записи контуров, которых больше нет
    в исходном DXF.

    Вся операция выполняется в одной транзакции:
    если импорт завершается ошибкой, изменения откатываются.

    Возвращает количество импортированных контуров.
    """
    contours = extract_room_contours(plan)
    imported_handles = []

    if not contours:
        raise ValueError('На слое 02_ROOMS не найдено контуров')

    for contour in contours:
        # Используем DXF Handle как идентификатор объекта
        # внутри конкретного плана.
        # Это позволяет при повторном импорте обновлять контур,
        # а не создавать его копию.
        RoomContourModel.objects.update_or_create(
            floor_plan=plan,
            source_handle=contour['handle'],
            defaults={
                'geometry': {
                    'type': contour['type'],
                    'closed': contour['closed'],
                    'points': contour['points'],
                },
            },
        )

        imported_handles.append(contour['handle'])

    # Удаляем из базы контуры, которые были удалены
    # из исходного DXF после предыдущего импорта.
    RoomContourModel.objects.filter(
        floor_plan=plan,
    ).exclude(
        source_handle__in=imported_handles,
    ).delete()

    return len(imported_handles)


def dxf_to_svg_coordinates(plan, x, y):
    """
    Переводит координаты точки из исходной системы DXF в SVG.

    Использует сохранённую в плане coordinate_system:
    - границы исходного чертежа;
    - размеры и положение SVG viewBox.

    Рассчитывает единый масштаб по ширине и высоте,
    чтобы сохранить пропорции чертежа.

    Если после масштабирования остаётся свободное место,
    компенсирует его смещением по X и Y.

    Также учитывает инверсию оси Y:
    в DXF направление Y отличается от направления
    координат SVG.

    Возвращает координаты точки (svg_x, svg_y).
    """
    cs = plan.coordinate_system

    min_x = cs['min_x']
    min_y = cs['min_y']
    max_x = cs['max_x']
    max_y = cs['max_y']

    view_x, view_y, view_width, view_height = cs['viewBox']

    source_width = max_x - min_x
    source_height = max_y - min_y

    # Используем одинаковый масштаб по обеим осям,
    # чтобы геометрия не растягивалась и не искажалась.
    scale = min(
        view_width / source_width,
        view_height / source_height,
    )

    # Центрируем чертёж внутри viewBox SVG,
    # если его пропорции отличаются от пропорций исходного плана.
    offset_x = (view_width - source_width * scale) / 2
    offset_y = (view_height - source_height * scale) / 2

    # Инвертируем ось Y, поскольку направление координат
    # в исходном DXF противоположно направлению SVG.

    svg_x = view_x + offset_x + (x - min_x) * scale
    svg_y = view_y + offset_y + (max_y - y) * scale

    return svg_x, svg_y


def get_polygon_center(points):
    """
    Вычисляет геометрический центр многоугольника.

    Использует формулу центроида полигона на основе
    координат его вершин.

    Координаты должны быть предварительно преобразованы
    в систему SVG.

    Если площадь полигона близка к нулю, вместо формулы
    центроида возвращается среднее арифметическое координат
    вершин.

    Если точек меньше трёх, возвращает None.

    Используется для размещения номера помещения
    внутри его контура.
    """
    if len(points) < 3:
        return None

    area = 0
    center_x = 0
    center_y = 0

    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]

        cross = x1 * y2 - x2 * y1

        area += cross
        center_x += (x1 + x2) * cross
        center_y += (y1 + y2) * cross

    if abs(area) < 1e-9:
        return (
            sum(x for x, y in points) / len(points),
            sum(y for x, y in points) / len(points),
        )

    center_x /= 3 * area
    center_y /= 3 * area

    return center_x, center_y


def generate_room_contours_svg(plan):
    """
    Формирует SVG-слой контуров помещений для отображения на карте.

    Получает все активные контуры плана и для каждого:
    - преобразует координаты вершин из DXF в SVG;
    - формирует SVG path;
    - добавляет идентификаторы контура и помещения
      в HTML-атрибуты для взаимодействия с фронтендом;
    - замыкает path, если контур отмечен как замкнутый.

    Для замкнутых контуров, связанных с помещениями,
    дополнительно формирует маркер с номером помещения.

    Возвращает SVG-разметку в виде строки.
    """
    SVG_NS = 'http://www.w3.org/2000/svg'
    ET.register_namespace('', SVG_NS)

    contours = (
        plan.room_contours
        .filter(is_active=True)
        .select_related('room')
    )

    view_box = plan.coordinate_system['viewBox']

    # Получаем активные контуры текущего плана.
    # select_related('room') позволяет сразу загрузить
    # связанные помещения без дополнительных запросов в цикле.
    svg = ET.Element(
        f'{{{SVG_NS}}}svg',
        {
            'viewBox': ' '.join(map(str, view_box)),
            'preserveAspectRatio': 'xMidYMid meet',
            'class': 'room-contours-layer',
        },
    )

    # Переводим все вершины контура из координат DXF
    # в координаты SVG для правильного отображения поверх плана.
    for contour in contours:
        points = contour.geometry.get('points', [])

        if len(points) < 2:
            continue

        svg_points = [
            dxf_to_svg_coordinates(
                plan,
                point['x'],
                point['y'],
            )
            for point in points
        ]

        # Собираем SVG-команду построения линии через все вершины.
        # Для замкнутых контуров ниже будет добавлена команда Z.
        path_data = 'M ' + ' L '.join(
            f'{x:.3f},{y:.3f}'
            for x, y in svg_points
        )

        is_closed = contour.geometry.get('closed', False)

        if is_closed:
            path_data += ' Z'

        # Сохраняем ID контура и связанного помещения
        # в SVG-атрибутах. JavaScript использует их
        # для выбора контуров и открытия карточек помещений.
        ET.SubElement(
            svg,
            f'{{{SVG_NS}}}path',
            {
                'd': path_data,
                'data-contour-id': str(contour.id),
                'data-room-id': str(contour.room_id or ''),
                'class': 'room-contour',
            },
        )

        # Номер помещения отображаем только для замкнутого контура,
        # у которого есть привязанная запись помещения.
        if is_closed and contour.room:
            # Определяем центр контура, чтобы расположить
            # номер помещения внутри него.
            center = get_polygon_center(svg_points)

            if center:
                center_x, center_y = center
                room_number = str(contour.room.number)

                badge = ET.SubElement(
                    svg,
                    f'{{{SVG_NS}}}g',
                    {
                        'class': 'room-number-badge',
                    },
                )

                ET.SubElement(
                    badge,
                    f'{{{SVG_NS}}}circle',
                    {
                        'cx': f'{center_x:.3f}',
                        'cy': f'{center_y:.3f}',
                        'r': '10000',  # Радиус окружности с маркером помещения
                    },
                )

                text = ET.SubElement(
                    badge,
                    f'{{{SVG_NS}}}text',
                    {
                        'x': f'{center_x:.3f}',
                        'y': f'{center_y:.3f}',
                        'text-anchor': 'middle',
                        'dominant-baseline': 'central',
                        'style': 'font-size: 6500px !important; font-weight: 700;',
                    },
                )

                text.text = room_number

    return ET.tostring(svg, encoding='unicode')
