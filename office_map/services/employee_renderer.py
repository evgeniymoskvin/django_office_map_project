import xml.etree.ElementTree as ET

from django.contrib.staticfiles import finders
from django.templatetags.static import static

from office_map.services.dxf_converter import dxf_to_svg_coordinates
from office_map.services.employee_service import (
    get_employee_placements,
    get_employee_data,
)

"""
Формирование SVG-элементов сотрудников для отображения на плане этажа.

Модуль создаёт SVG-маркеры сотрудников с фотографиями или инициалами,
размещает их по координатам из модели и добавляет подписи с именами.
"""

SVG_NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', SVG_NS)

# Путь к стандартному изображению, используемому при отсутствии фотографии.
PLACEHOLDER_PATH = 'office_map/img/no-photo.png'

# Диаметр маркера сотрудника в миллиметрах DXF.
AVATAR_DIAMETER_MM = 800


def svg_tag(name):
    """Возвращает имя SVG-тега с пространством имён SVG."""
    return f'{{{SVG_NS}}}{name}'


def get_initials(employee_data):
    """
    Формирует инициалы сотрудника из фамилии и имени.
    Используется для отображения вместо фотографии, если она недоступна.
    """

    last_name = employee_data.get('last_name') or ''
    first_name = employee_data.get('first_name') or ''
    initials = last_name[:1] + first_name[:1]
    return initials.upper() or '?'


def get_placeholder_url():
    if finders.find(PLACEHOLDER_PATH):
        return static(PLACEHOLDER_PATH)
    return None


def _get_avatar_radius(plan):
    """
    Рассчитывает радиус аватара в координатах SVG.
    Учитывает размеры исходного плана и его масштабирование
    при преобразовании координат DXF в SVG.
    """

    coordinate_system = plan.coordinate_system

    min_x = float(coordinate_system['min_x'])
    max_x = float(coordinate_system['max_x'])
    min_y = float(coordinate_system['min_y'])
    max_y = float(coordinate_system['max_y'])

    view_box = coordinate_system.get(
        'viewBox',
        [0, 0, 1000000, 750000],
    )

    view_width = float(view_box[2])
    view_height = float(view_box[3])

    source_width = max_x - min_x
    source_height = max_y - min_y

    scale = min(
        view_width / source_width,
        view_height / source_height,
    )

    return AVATAR_DIAMETER_MM * scale / 2


def _build_employee_group(
        plan,
        placement,
        employee_data,
        avatar_radius,
        placeholder_url,
):
    """
    Создаёт SVG-группу одного сотрудника.

    В группу входят:
    - маркер с фоновым кругом;
    - фотография сотрудника или его инициалы;
    - обводка аватара;
    - подпись с фамилией и инициалами.

    Координаты размещения преобразуются из DXF в SVG.
    Атрибуты data-* используются JavaScript для идентификации
    сотрудника и управления его положением на карте.
    """

    svg_x, svg_y = dxf_to_svg_coordinates(
        plan,
        placement.x,
        placement.y,
    )

    # Преобразуем координаты размещения сотрудника из DXF в SVG.
    group = ET.Element(
        svg_tag('g'),
        {
            'class': 'employee-debug',
            'data-placement-id': str(placement.pk),
            'data-employee-id': str(placement.employee_id),
            'data-x': str(placement.x),
            'data-y': str(placement.y),
            'data-base-x': str(placement.x),
            'data-base-y': str(placement.y),
            'data-full-name': employee_data['full_name'],
            'data-job-title': employee_data['job_title'],
            'transform': f'translate({svg_x} {svg_y})',
        },
    )

    # Уникальный идентификатор обрезки фотографии для конкретного сотрудника.
    clip_id = f'employee-clip-{placement.pk}'

    defs = ET.SubElement(group, svg_tag('defs'))

    # Ограничиваем фотографию круглой областью аватара.
    clip_path = ET.SubElement(
        defs,
        svg_tag('clipPath'),
        {
            'id': clip_id,
            'clipPathUnits': 'userSpaceOnUse',
        },
    )

    # Создаём фон маркера, который остаётся виден под фотографией.
    ET.SubElement(
        clip_path,
        svg_tag('circle'),
        {
            'cx': '0',
            'cy': '0',
            'r': str(avatar_radius),
        },
    )

    ET.SubElement(
        group,
        svg_tag('circle'),
        {
            'class': 'employee-marker-background',
            'cx': '0',
            'cy': '0',
            'r': str(avatar_radius),
        },
    )

    # Используем фотографию сотрудника или стандартное изображение-заглушку.
    image_url = employee_data.get('photo_url') or placeholder_url

    # Если изображение доступно, вставляем его в SVG с круглой обрезкой.
    # В противном случае отображаем инициалы сотрудника.
    if image_url:
        ET.SubElement(
            group,
            svg_tag('image'),
            {
                'class': 'employee-avatar',
                'href': image_url,
                'x': str(-avatar_radius),
                'y': str(-avatar_radius),
                'width': str(avatar_radius * 2),
                'height': str(avatar_radius * 2),
                'preserveAspectRatio': 'xMidYMid slice',
                'clip-path': f'url(#{clip_id})',
            },
        )
    else:
        initials = ET.SubElement(
            group,
            svg_tag('text'),
            {
                'class': 'employee-initials',
                'x': '0',
                'y': str(avatar_radius * 0.35),
                'text-anchor': 'middle',
                'font-size': str(avatar_radius * 0.75),
            },
        )
        initials.text = get_initials(employee_data)

    # Добавляем обводку поверх фотографии или инициалов.
    ET.SubElement(
        group,
        svg_tag('circle'),
        {
            'class': 'employee-marker-border',
            'cx': '0',
            'cy': '0',
            'r': str(avatar_radius),
        },
    )

    # Подготавливаем фамилию и инициалы для подписи под аватаром.
    first_name = employee_data.get('first_name') or ''
    middle_name = employee_data.get('middle_name') or ''
    last_name = employee_data.get('last_name') or ''

    initials = ''.join(
        f'{name[0].upper()}. '
        for name in (first_name, middle_name)
        if name
    ).strip()

    label_text = ' '.join(
        part for part in (last_name, initials) if part
    )

    # Добавляем подпись сотрудника под маркером.

    label_font_size = avatar_radius * 0.45
    label_y = avatar_radius + avatar_radius * 0.65

    # Приблизительно рассчитываем ширину текста с учётом его длины.
    label_width = max(
        len(label_text) * label_font_size * 0.6,
        label_font_size,
    )

    # Размеры белой подложки с небольшими отступами.
    padding_x = label_font_size * 0.35
    padding_y = label_font_size * 0.2

    background_width = label_width + padding_x * 2
    background_height = label_font_size + padding_y * 2

    # Белая подложка располагается за текстом.
    ET.SubElement(
        group,
        svg_tag('rect'),
        {
            'class': 'employee-label-background',
            'x': str(-background_width / 2),
            'y': str(label_y - label_font_size * 0.85 - padding_y),
            'width': str(background_width),
            'height': str(background_height),
            'rx': str(label_font_size * 0.2),
            'fill': '#FFFFFF',
            'fill-opacity': '0.95',
            'stroke': 'none',
        },
    )

    # Сам текст располагается поверх белой подложки.
    label = ET.SubElement(
        group,
        svg_tag('text'),
        {
            'class': 'employee-label',
            'x': '0',
            'y': str(label_y),
            'text-anchor': 'middle',
            'font-size': str(label_font_size),
        },
    )
    label.text = label_text

    return group


def generate_employee_placement_svg(plan, placement):
    """
    Генерирует SVG одного сотрудника для динамической вставки на карту.
    Получает данные сотрудника, рассчитывает размер аватара
    и создаёт SVG-группу с фотографией или инициалами и подписью.
    Возвращает SVG в виде строки.
    """

    employee_data = get_employee_data(placement)
    avatar_radius = _get_avatar_radius(plan)
    placeholder_url = get_placeholder_url()

    group = _build_employee_group(
        plan=plan,
        placement=placement,
        employee_data=employee_data,
        avatar_radius=avatar_radius,
        placeholder_url=placeholder_url,
    )

    return ET.tostring(
        group,
        encoding='unicode',
        method='xml',
    )


def generate_employee_svg(plan):
    """
    Генерирует полный SVG-слой сотрудников для этажа.
    Создаёт корневой SVG-элемент с координатами плана,
    получает все активные размещения сотрудников на этаже
    и добавляет для каждого отдельную SVG-группу.
    Возвращает готовый SVG в виде строки.
    """

    coordinate_system = plan.coordinate_system

    view_box = coordinate_system.get(
        'viewBox',
        [0, 0, 1000000, 750000],
    )

    root = ET.Element(
        svg_tag('svg'),
        {
            'viewBox': ' '.join(map(str, view_box)),
            'preserveAspectRatio': 'xMidYMid meet',
            'class': 'employee-layer',
            'data-min-x': str(coordinate_system['min_x']),
            'data-min-y': str(coordinate_system['min_y']),
            'data-max-x': str(coordinate_system['max_x']),
            'data-max-y': str(coordinate_system['max_y']),
        },
    )

    avatar_radius = _get_avatar_radius(plan)
    placeholder_url = get_placeholder_url()

    # Создаём корневой SVG-элемент и задаём систему координат плана.
    for placement in get_employee_placements(plan):
        employee_data = get_employee_data(placement)

        group = _build_employee_group(
            plan=plan,
            placement=placement,
            employee_data=employee_data,
            avatar_radius=avatar_radius,
            placeholder_url=placeholder_url,
        )

        root.append(group)

    return ET.tostring(
        root,
        encoding='unicode',
        method='xml',
    )
