import json
import math
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET, require_POST
from django.template.loader import render_to_string
from django.db.models import Q
from django.urls import reverse
from urllib.parse import urlencode

from django.utils import timezone
from apps.legacy_models.models import VacationsModel

from apps.legacy_models.models import EmployeeModel

from .models import (
    BuildingModel,
    EmployeePlacementModel,
    FloorModel,
    FloorPlanModel,
    FurnitureModel,
    FurniturePlacementModel,
    RoomContourModel,
    RoomModel,
)

from .services.dxf_converter import generate_room_contours_svg
from .services.employee_renderer import generate_employee_svg

from .services.furniture_renderer import (
    generate_furniture_svg,
    generate_furniture_placement_svg,
    generate_furniture_preview_svg,
)
from .services.permissions import can_edit_layout

from office_map.services.employee_renderer import (
    generate_employee_placement_svg,
)

from office_map.services.employee_service import (
    get_employee_placements,
    get_employee_data,
    get_available_employees,
)


def point_in_polygon(x, y, points):
    """
    Проверяет, находится ли точка внутри многоугольника.

    Используется для определения:
    - к какому помещению относится размещённый сотрудник;
    - в каком помещении находится сотрудник при переходе
      к нему через глобальный поиск.

    Координаты точки и вершин многоугольника передаются
    в исходной системе координат DXF.
    """
    inside = False
    count = len(points)

    if count < 3:
        return False

    j = count - 1

    for i in range(count):
        xi = points[i]['x']
        yi = points[i]['y']
        xj = points[j]['x']
        yj = points[j]['y']

        intersects = (
                (yi > y) != (yj > y)
                and x < (xj - xi) * (y - yi) / (yj - yi) + xi
        )

        if intersects:
            inside = not inside

        j = i

    return inside


def map_home(request):
    """
    Главная страница карты офиса.

    Для авторизованного пользователя пытается определить
    его активное размещение на плане и сразу открыть
    соответствующий этаж.

    Если пользователь не авторизован, не найден в телефонном
    справочнике или не имеет активного размещения,
    отображается страница выбора здания и этажа.
    """
    if request.user.is_authenticated:
        try:
            employee = request.user.phonebook_emp_user
        except EmployeeModel.DoesNotExist:
            employee = None

        if employee and employee.work_status:
            placement = (
                EmployeePlacementModel.objects
                .filter(
                    employee=employee,
                    is_active=True,
                    floor_plan__is_active=True,
                )
                .select_related('floor_plan__floor__building')
                .first()
            )

            if placement:
                return redirect(
                    'office_map:floor_detail',
                    floor_id=placement.floor_plan.floor_id,
                )

    buildings = (
        BuildingModel.objects.all()
    )

    return render(
        request,
        'office_map/map_home.html',
        {'buildings': buildings},
    )


@xframe_options_sameorigin
def floor_detail(request, floor_id):
    """
    Отображает план выбранного этажа.

    Находит активный план этажа и подготавливает SVG-слои:
    - контуры помещений;
    - мебель;
    - размещённых сотрудников.

    Дополнительно обрабатывает параметры URL:
    - embed=1 — режим встраивания карты;
    - focus_employee — ID размещения сотрудника,
      к которому нужно перейти.

    Если передан focus_employee, определяет, внутри какого
    контура помещения находятся координаты сотрудника.
    Это позволяет после перехода подсветить нужное помещение.

    В шаблон также передаются список зданий и этажей,
    а также информация о правах пользователя на редактирование.
    """
    floor = get_object_or_404(
        FloorModel.objects.select_related('building'),
        id=floor_id,
    )

    # Получаем последний активный план этажа.
    # Планы без SVG-файла не подходят для отображения карты.
    plan = (
        FloorPlanModel.objects
        .filter(
            floor=floor,
            is_active=True,
        )
        .exclude(svg_file='')
        .order_by('-created_at')
        .first()
    )

    has_plan = bool(plan and plan.coordinate_system)

    furniture_svg = (
        generate_furniture_svg(plan)
        if has_plan
        else ''
    )

    # Проверяем, готов ли план к отображению.
    # coordinate_system содержит границы и параметры системы координат.
    # Без неё нельзя корректно отобразить объекты на плане.
    contours_svg = (
        generate_room_contours_svg(plan)
        if has_plan
        else ''
    )

    employees_svg = (
        generate_employee_svg(plan)
        if has_plan
        else ''
    )

    embed = request.GET.get('embed') == '1'

    focus_employee_placement = None
    focus_contour_id = None

    # Если пользователь перешёл к сотруднику из глобального поиска,
    # находим его размещение на текущем плане.
    # UUID проверяется отдельно, чтобы некорректный параметр URL
    # не приводил к ошибке при запросе к базе.
    focus_employee_id = request.GET.get('focus_employee')

    if has_plan and focus_employee_id:
        try:
            focus_employee_uuid = UUID(focus_employee_id)
        except (ValueError, TypeError, AttributeError):
            focus_employee_uuid = None

        if focus_employee_uuid:
            focus_employee_placement = (
                EmployeePlacementModel.objects
                .filter(
                    id=focus_employee_uuid,
                    floor_plan=plan,
                    is_active=True,
                    employee__work_status=True,
                )
                .select_related('employee')
                .first()
            )

        if focus_employee_placement:
            contours = RoomContourModel.objects.filter(
                floor_plan=plan,
                is_active=True,
            )

            # Ищем контур помещения, внутри которого расположены
            # координаты сотрудника. Проверяем только замкнутые контуры.
            for contour in contours:
                geometry = contour.geometry or {}
                points = geometry.get('points', [])

                if not geometry.get('closed', False):
                    continue

                if point_in_polygon(
                        focus_employee_placement.x,
                        focus_employee_placement.y,
                        points,
                ):
                    focus_contour_id = str(contour.id)
                    break

    buildings = (
        BuildingModel.objects
        .prefetch_related('floors')
        .order_by('name')
    )

    return render(
        request,
        'office_map/floor.html',
        {
            'floor': floor,
            'building': floor.building,
            'plan': plan,
            'contours_svg': contours_svg,
            'furniture_svg': furniture_svg,
            'employees_svg': employees_svg,
            'embed': embed,
            'can_edit_layout': can_edit_layout(
                request.user,
                building=floor.building,
                floor=floor,
            ),
            'focus_employee_placement': focus_employee_placement,
            'focus_contour_id': focus_contour_id,
            'buildings': buildings,
        },
    )


def parse_coordinates(request):
    """
    Извлекает координаты X и Y из JSON-тела POST-запроса.

    Проверяет, что координаты:
    - присутствуют в запросе;
    - могут быть преобразованы в числа;
    - являются конечными числами (не NaN и не Infinity).

    Возвращает кортеж (x, y), если данные корректны.
    При ошибке возвращает None.

    Используется при перемещении и добавлении объектов на плане.
    """
    try:
        data = json.loads(request.body)

        x = float(data['x'])
        y = float(data['y'])

        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError('Некорректные координаты')

        return x, y

    except (
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
    ):
        return None


@require_POST
def move_furniture(request, placement_id):
    """
    Сохраняет новые координаты уже размещённого предмета мебели.

    Получает размещение по ID, проверяет права пользователя
    на редактирование конкретного этажа, проверяет координаты
    из POST-запроса и сохраняет их в базе.

    В ответ возвращает результат операции и новые координаты.
    """

    placement = get_object_or_404(
        FurniturePlacementModel.objects.select_related(
            'floor_plan__floor__building',
        ),
        id=placement_id,
    )

    floor = placement.floor_plan.floor
    building = floor.building

    if not can_edit_layout(request.user, building, floor):
        return JsonResponse(
            {
                'success': False,
                'error': 'Недостаточно прав для перемещения объектов.',
            },
            status=403,
        )

    coordinates = parse_coordinates(request)

    if coordinates is None:
        return JsonResponse(
            {
                'success': False,
                'error': 'Некорректные координаты',
            },
            status=400,
        )

    placement.x, placement.y = coordinates
    placement.save(update_fields=['x', 'y'])

    return JsonResponse({
        'success': True,
        'x': placement.x,
        'y': placement.y,
        'can_edit_layout': can_edit_layout(request.user, building, floor),
    })


@require_POST
def move_employee(request, placement_id):
    """
    Перемещает уже размещённого сотрудника на плане этажа.

    Проверяет, что размещение активно, и что пользователь имеет
    право редактировать соответствующий этаж.

    После проверки координат сохраняет новое положение сотрудника
    и возвращает его координаты в JSON-ответе.
    """
    placement = get_object_or_404(
        EmployeePlacementModel.objects.select_related(
            'floor_plan__floor__building',
        ),
        id=placement_id,
        is_active=True,
    )

    floor = placement.floor_plan.floor
    building = floor.building

    if not can_edit_layout(request.user, building, floor):
        return JsonResponse(
            {
                'success': False,
                'error': 'Недостаточно прав для перемещения объектов.',
            },
            status=403,
        )

    coordinates = parse_coordinates(request)

    if coordinates is None:
        return JsonResponse(
            {
                'success': False,
                'error': 'Некорректные координаты',
            },
            status=400,
        )

    placement.x, placement.y = coordinates
    placement.save(update_fields=['x', 'y'])

    return JsonResponse({
        'success': True,
        'x': placement.x,
        'y': placement.y,
        'can_edit_layout': can_edit_layout(
            request.user,
            building=building,
            floor=floor,
        ),
    })


def calculate_polygon_area_m2(points):
    """
    Рассчитывает площадь помещения по координатам его контура.

    Использует формулу площади многоугольника (формулу Гаусса).
    Координаты вершин берутся из геометрии контура в исходных
    единицах DXF — миллиметрах.

    Результат переводится из мм² в м² и округляется до
    двух знаков после запятой.

    Если точек недостаточно для построения многоугольника,
    возвращает None.
    """

    if not points or len(points) < 3:
        return None

    area = 0.0
    count = len(points)

    for i in range(count):
        current = points[i]
        next_point = points[(i + 1) % count]

        area += (
                float(current['x']) * float(next_point['y'])
                - float(next_point['x']) * float(current['y'])
        )

    area_mm2 = abs(area) / 2

    return round(area_mm2 / 1_000_000, 2)


@require_GET
def room_detail(request, contour_id):
    """
    Формирует данные для боковой панели выбранного помещения.

    По ID контура получает связанное помещение и проверяет,
    имеет ли пользователь право редактировать план.

    Дополнительно:
    - рассчитывает площадь замкнутого контура;
    - находит сотрудников, координаты которых находятся внутри
      контура помещения;
    - сравнивает номер помещения с кабинетом из кадровой карточки;
    - при наличии прав формирует список свободных помещений,
      которые можно привязать к этому контуру.

    HTML боковой панели формируется Django-шаблоном
    room_panel.html и возвращается вместе с данными в JSON.

    Параметр edit=1 в GET-запросе включает режим редактирования
    привязки помещения.
    """

    contour = get_object_or_404(
        RoomContourModel.objects.select_related(
            'room',
            'floor_plan__floor__building',
        ),
        id=contour_id,
        is_active=True,
    )

    floor = contour.floor_plan.floor
    building = floor.building

    can_edit = can_edit_layout(
        request.user,
        building=building,
        floor=floor,
    )

    geometry = contour.geometry or {}
    points = geometry.get('points', [])
    is_closed = geometry.get('closed', False)

    area_m2 = (
        calculate_polygon_area_m2(points)
        if is_closed
        else None
    )

    room = contour.room
    room_number = str(room.number).strip() if room else ''

    # Получаем сотрудников, размещённых на текущем плане,
    # и оставляем только тех, чьи координаты находятся внутри
    # выбранного контура помещения.

    employees = []

    if is_closed and len(points) >= 3:
        placements = get_employee_placements(contour.floor_plan)

        for placement in placements:
            if not point_in_polygon(placement.x, placement.y, points):
                continue

            employee = get_employee_data(placement)

            # Сравниваем помещение, указанное в кадровой карточке
            # сотрудника, с помещением, которому принадлежит контур.
            # Это позволяет обнаружить возможное несоответствие данных.
            legacy_room = str(employee.get('room') or '').strip()
            employee['legacy_room'] = legacy_room
            employee['room_mismatch'] = bool(
                room_number
                and legacy_room
                and room_number.casefold() != legacy_room.casefold()
            )

            employees.append(employee)

    # Для режима редактирования получаем помещения этажа,
    # которые ещё не привязаны к другим активным контурам.
    # Текущее помещение исключаем из проверки, чтобы его можно
    # было оставить привязанным к тому же контуру.
    available_rooms = []

    if can_edit:
        assigned_room_ids = RoomContourModel.objects.filter(
            is_active=True,
            floor_plan__floor=floor,
            room__isnull=False,
        ).exclude(
            id=contour.id,
        ).values_list(
            'room_id',
            flat=True,
        )

        available_rooms = [
            {
                'id': str(item.id),
                'number': item.number,
                'name': item.name,
            }
            for item in RoomModel.objects.filter(
                floor=floor,
            ).exclude(
                id__in=assigned_room_ids,
            ).order_by('number')
        ]

    room_edit_mode = request.GET.get('edit') == '1'

    # Формируем HTML боковой панели на стороне Django.
    # Фронтенд получает готовую разметку и вставляет её в панель.

    room_html = render_to_string(
        'office_map/partials/room_panel.html',
        {
            'room': room,
            'employees': employees,
            'area_m2': area_m2,
            'can_edit': can_edit,
            'available_rooms': available_rooms,
            'room_edit_mode': room_edit_mode,
        },
        request=request,
    )

    return JsonResponse({
        'success': True,
        'room': {
            'id': str(room.id) if room else None,
            'number': room.number if room else None,
            'name': room.name if room else '',
            'description': room.description if room else '',
            'area_m2': area_m2,
        } if room else None,
        'employees': employees,
        'has_room': room is not None,
        'can_edit': can_edit,
        'available_rooms': available_rooms,
        'html': room_html,
    })


@login_required
@require_POST
def assign_room_to_contour(request, contour_id):
    """
    Привязывает помещение к выбранному контуру или снимает привязку.

    Получает ID помещения из JSON POST-запроса.

    Перед сохранением проверяет:
    - права пользователя на редактирование этажа;
    - корректность ID помещения;
    - принадлежность помещения выбранному этажу;
    - отсутствие привязки этого помещения к другому
      активному контуру на том же этаже.

    Если room_id не передан или имеет пустое значение,
    привязка помещения к контуру снимается.

    Возвращает JSON с результатом операции.
    """

    contour = get_object_or_404(
        RoomContourModel.objects.select_related(
            'floor_plan__floor__building',
        ),
        id=contour_id,
        is_active=True,
    )

    floor = contour.floor_plan.floor
    building = floor.building

    if not can_edit_layout(
            request.user,
            building=building,
            floor=floor,
    ):
        return JsonResponse(
            {'success': False, 'error': 'Недостаточно прав'},
            status=403,
        )

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse(
            {'success': False, 'error': 'Некорректные данные'},
            status=400,
        )

    room_id = data.get('room_id')

    if room_id:
        try:
            room_uuid = UUID(str(room_id))
        except (ValueError, TypeError, AttributeError):
            return JsonResponse(
                {'success': False, 'error': 'Некорректный ID помещения'},
                status=400,
            )

        room = get_object_or_404(
            RoomModel,
            id=room_uuid,
            floor=floor,
        )

        # Проверяем, не привязано ли помещение к другому контуру
        already_assigned = (RoomContourModel.objects
                            .filter(room=room, is_active=True, )
                            .exclude(id=contour.id, )).exists()

        # Одно помещение не должно быть привязано сразу к нескольким
        # активным контурам на одном этаже.
        # Текущий контур исключаем из проверки, поскольку помещение
        # может уже быть привязано именно к нему.

        if already_assigned:
            return JsonResponse(
                {
                    'success': False,
                    'error': (
                        f'Помещение {room.number} уже привязано '
                        'к другому контуру.'
                    ),
                },
                status=409,
            )

    else:
        room = None

    contour.room = room
    contour.save(update_fields=['room'])

    return JsonResponse({
        'success': True,
        'room': {
            'id': str(room.id),
            'number': room.number,
            'name': room.name,
            'description': room.description,
        } if room else None,
    })


@require_GET
def employee_detail(request, placement_id):
    """
    Возвращает данные для карточки выбранного сотрудника.

    По ID размещения находит сотрудника и проверяет,
    что размещение активно, а сотрудник продолжает работать.

    Данные сотрудника получает через get_employee_data(),
    после чего формирует HTML карточки с помощью шаблона
    employee_detail.html.

    Возвращает готовую HTML-разметку в JSON-ответе.
    """
    placement = get_object_or_404(
        EmployeePlacementModel.objects.select_related('employee'),
        id=placement_id,
        is_active=True,
        employee__work_status=True,
    )

    employee = get_employee_data(placement)

    today = timezone.localdate()

    vacation = VacationsModel.objects.filter(
        employee=placement.employee,
        vacation_start__lte=today,
        vacation_end__gte=today,
    ).first()

    html = render_to_string(
        'office_map/partials/employee_detail.html',
        {
            'employee': employee,
            'vacation': vacation,
        },
        request=request,
    )

    return JsonResponse({
        'success': True,
        'html': html,
    })


@require_POST
def rotate_furniture(request, placement_id):
    """
    Изменяет угол поворота уже размещённого предмета мебели.

    Получает размещение по ID и проверяет права пользователя
    на редактирование соответствующего этажа.

    Угол поворота передаётся в JSON POST-запросе.
    Проверяется корректность значения, после чего угол
    приводится к диапазону от 0 до 359 градусов.

    Сохраняет новое значение в базе и возвращает его в JSON.
    """
    placement = get_object_or_404(
        FurniturePlacementModel.objects.select_related(
            'floor_plan__floor__building'
        ),
        id=placement_id,
        is_active=True,
    )

    floor = placement.floor_plan.floor
    building = floor.building

    if not can_edit_layout(
            request.user,
            building=building,
            floor=floor,
    ):
        return JsonResponse(
            {'success': False, 'error': 'Недостаточно прав'},
            status=403,
        )

    try:
        data = json.loads(request.body)
        rotation = float(data.get('rotation'))
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse(
            {'success': False, 'error': 'Некорректный угол поворота'},
            status=400,
        )

    if not math.isfinite(rotation):
        return JsonResponse(
            {'success': False, 'error': 'Некорректный угол поворота'},
            status=400,
        )

    placement.rotation = rotation % 360
    placement.save(update_fields=['rotation'])

    return JsonResponse({
        'success': True,
        'rotation': placement.rotation,
    })


@require_GET
def furniture_catalog(request, floor_id):
    """
    Возвращает каталог доступной мебели для выбранного этажа.

    Получает этаж и его активный план.
    Формирует список активных моделей мебели с параметрами:
    - ID и название;
    - ширина и высота;
    - SVG-превью для отображения в каталоге.

    HTML каталога формируется шаблоном furniture_catalog.html
    и возвращается в JSON-ответе.
    """
    floor = get_object_or_404(FloorModel, id=floor_id)

    # Подготавливаем данные всех активных моделей мебели.
    # Для каждого элемента отдельно генерируем SVG-превью,
    # которое используется в каталоге на фронтенде.

    items = [
        {
            'id': str(item.id),
            'name': item.name,
            'width_mm': item.width_mm,
            'height_mm': item.height_mm,
            'preview_svg': generate_furniture_preview_svg(item),
        }
        for item in FurnitureModel.objects.filter(
            is_active=True,
        ).order_by('name')
    ]

    html = render_to_string(
        'office_map/partials/furniture_catalog.html',
        {'items': items},
        request=request,
    )

    return JsonResponse({
        'success': True,
        'html': html,
    })


@require_POST
def add_furniture(request, floor_id):
    """
    Создаёт новое размещение выбранной модели мебели на плане этажа.

    Получает из POST-запроса:
    - ID модели мебели;
    - координаты X и Y для размещения.

    Проверяет права пользователя, корректность входных данных
    и наличие геометрии у выбранной модели.

    После создания размещения генерирует SVG конкретного
    экземпляра мебели для добавления на карту без перезагрузки.

    Если SVG не удалось сформировать, созданное размещение
    удаляется, чтобы в базе не осталось некорректного объекта.
    """

    floor = get_object_or_404(
        FloorModel.objects.select_related('building'),
        id=floor_id,
    )

    plan = get_object_or_404(
        FloorPlanModel,
        floor=floor,
        is_active=True,
    )

    if not can_edit_layout(
            request.user,
            building=floor.building,
            floor=floor,
    ):
        return JsonResponse(
            {
                'success': False,
                'error': 'Недостаточно прав для добавления мебели.',
            },
            status=403,
        )

    try:
        data = json.loads(request.body)
        furniture_id = data['furniture_id']
    except (json.JSONDecodeError, TypeError, KeyError):
        return JsonResponse(
            {
                'success': False,
                'error': 'Некорректные данные запроса.',
            },
            status=400,
        )

    coordinates = parse_coordinates(request)

    if coordinates is None:
        return JsonResponse(
            {
                'success': False,
                'error': 'Некорректные координаты.',
            },
            status=400,
        )

    try:
        furniture_uuid = UUID(str(furniture_id))
    except (ValueError, TypeError, AttributeError):
        return JsonResponse(
            {
                'success': False,
                'error': 'Некорректный ID мебели.',
            },
            status=400,
        )

    furniture = get_object_or_404(
        FurnitureModel,
        id=furniture_uuid,
        is_active=True,
    )

    if not isinstance(furniture.geometry, list) or not furniture.geometry:
        return JsonResponse(
            {
                'success': False,
                'error': 'У выбранной мебели отсутствует геометрия.',
            },
            status=400,
        )

    x, y = coordinates

    # Создаём запись размещения мебели на плане.
    # Координаты задаются в системе координат исходного DXF,
    # начальный угол поворота — 0 градусов.

    placement = FurniturePlacementModel.objects.create(
        floor_plan=plan,
        furniture=furniture,
        x=x,
        y=y,
        rotation=0,
        is_active=True,
    )

    # Формируем SVG нового экземпляра мебели с учётом его
    # положения и параметров исходной модели.
    placement_svg = generate_furniture_placement_svg(
        plan,
        placement,
    )

    if not placement_svg:
        placement.delete()
        return JsonResponse(
            {
                'success': False,
                'error': 'Не удалось построить SVG мебели.',
            },
            status=400,
        )

    return JsonResponse({
        'success': True,
        'placement_id': str(placement.id),
        'furniture_svg': placement_svg,
        'x': placement.x,
        'y': placement.y,
        'rotation': placement.rotation,
    })


@require_POST
def delete_furniture(request, placement_id):
    """
    Удаляет размещённый предмет мебели с плана.

    Физически запись из базы не удаляется:
    размещение помечается неактивным (is_active=False).

    Такой подход сохраняет историю размещений и позволяет
    отличать удалённые объекты от действующих.
    """
    if not can_edit_layout(request.user):
        return JsonResponse(
            {'success': False, 'error': 'Недостаточно прав'},
            status=403,
        )

    placement = get_object_or_404(
        FurniturePlacementModel,
        id=placement_id,
        is_active=True,
    )

    # placement.is_active = False
    # placement.save(update_fields=['is_active'])
    placement.delete()

    return JsonResponse({'success': True})


@require_GET
def employee_catalog(request, floor_id):
    """
    Возвращает каталог сотрудников, которых можно разместить
    на плане выбранного этажа.

    Получает список свободных работающих сотрудников
    через get_available_employees().

    Для каждого сотрудника формирует инициалы, которые
    используются в каталоге, если фотография отсутствует.

    HTML каталога формируется шаблоном employee_catalog.html.
    """

    if not can_edit_layout(request.user):
        return JsonResponse(
            {'success': False, 'error': 'Недостаточно прав'},
            status=403,
        )

    plan = get_object_or_404(
        FloorPlanModel,
        floor_id=floor_id,
        is_active=True,
    )

    employees = get_available_employees()

    for employee in employees:
        employee['initials'] = (
                                       (employee.get('last_name') or '')[:1]
                                       + (employee.get('first_name') or '')[:1]
                               ).upper() or '?'

    html = render_to_string(
        'office_map/partials/employee_catalog.html',
        {'employees': employees},
        request=request,
    )

    return JsonResponse({
        'success': True,
        'html': html,
    })


@require_POST
def add_employee(request, floor_id):
    """
    Размещает сотрудника на плане выбранного этажа.

    Получает из POST-запроса ID сотрудника и координаты X/Y,
    в которых нужно разместить его на карте.

    Перед созданием размещения проверяет:
    - права пользователя на редактирование;
    - корректность переданных данных и координат;
    - нахождение координат в пределах плана;
    - наличие сотрудника в кадровом справочнике;
    - отсутствие другого активного размещения этого сотрудника.

    Создание записи выполняется внутри транзакции.
    После сохранения генерируется SVG сотрудника для отображения
    на карте без перезагрузки страницы.

    Если генерация SVG завершается ошибкой, созданная запись
    удаляется, а ошибка передаётся дальше.
    """

    if not can_edit_layout(request.user):
        return JsonResponse(
            {'success': False, 'error': 'Недостаточно прав'},
            status=403,
        )

    plan = get_object_or_404(
        FloorPlanModel,
        floor_id=floor_id,
        is_active=True,
    )

    try:
        data = json.loads(request.body)

        employee_id = data.get('employee_id')
        x = float(data.get('x'))
        y = float(data.get('y'))

        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError

    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse(
            {'success': False, 'error': 'Некорректные данные'},
            status=400,
        )

    # Проверяем, что точка размещения находится внутри границ плана.
    # Границы берутся из coordinate_system активного плана.
    coordinate_system = plan.coordinate_system

    if not (
            coordinate_system['min_x'] <= x <= coordinate_system['max_x']
            and coordinate_system['min_y'] <= y <= coordinate_system['max_y']
    ):
        return JsonResponse(
            {'success': False, 'error': 'Координаты за пределами плана'},
            status=400,
        )

    employee = get_object_or_404(
        EmployeeModel,
        pk=employee_id,
        work_status=True,
    )

    # Один сотрудник может иметь только одно активное размещение
    # на планах офиса. Не допускаем повторного добавления.
    if EmployeePlacementModel.objects.filter(
            employee=employee,
            is_active=True,
    ).exists():
        return JsonResponse(
            {
                'success': False,
                'error': 'Сотрудник уже размещён на плане',
            },
            status=400,
        )

    # Создаём размещение в транзакции, чтобы операция сохранения
    # выполнялась целиком или не выполнялась вовсе.

    try:
        with transaction.atomic():
            placement = EmployeePlacementModel.objects.create(
                employee=employee,
                floor_plan=plan,
                x=x,
                y=y,
                is_active=True,
            )

    except IntegrityError:
        return JsonResponse(
            {
                'success': False,
                'error': 'Не удалось разместить сотрудника. Возможно, он уже размещён.',
            },
            status=400,
        )

    # После сохранения записи формируем SVG сотрудника
    # для добавления его изображения на карту.
    # При ошибке генерации удаляем созданное размещение.

    try:
        employee_svg = generate_employee_placement_svg(
            plan,
            placement,
        )
    except Exception:
        placement.delete()
        raise

    return JsonResponse({
        'success': True,
        'placement_id': str(placement.pk),
        'employee_id': employee.pk,
        'x': placement.x,
        'y': placement.y,
        'employee_svg': employee_svg,
    })


@require_POST
def delete_employee(request, placement_id):
    """
    Удаляет размещение сотрудника с плана.

    Находит активное размещение, определяет его этаж и здание,
    проверяет права пользователя на редактирование.

    Запись физически не удаляется из базы:
    размещение помечается неактивным (is_active=False).
    """
    placement = get_object_or_404(
        EmployeePlacementModel.objects.select_related(
            'floor_plan__floor__building',
        ),
        id=placement_id,
        is_active=True,
    )

    floor = placement.floor_plan.floor
    building = floor.building

    if not can_edit_layout(request.user, building, floor):
        return JsonResponse(
            {
                'success': False,
                'error': 'Недостаточно прав для удаления сотрудника.',
            },
            status=403,
        )

    # placement.is_active = False
    # placement.save(update_fields=['is_active'])
    placement.delete()

    return JsonResponse({'success': True})


@require_GET
def employee_search(request):
    """
    Выполняет глобальный поиск работающих сотрудников.

    Получает поисковую строку из GET-параметра q.
    Поиск выполняется по нескольким полям:
    - фамилия, имя и отчество;
    - должность;
    - подразделение;
    - группа подразделения.

    Если запрос состоит из нескольких слов, каждое слово
    должно совпасть хотя бы с одним из поисковых полей.

    Для найденных сотрудников дополнительно определяет:
    - наличие активного размещения на плане;
    - здание и этаж размещения;
    - кабинет из кадровой карточки.

    Результаты передаются в шаблон global_search_employee_results.html.
    Фронтенд получает готовую HTML-разметку в JSON-ответе.
    """

    query = request.GET.get('q', '').strip()

    if len(query) < 2:
        return JsonResponse({
            'success': True,
            'employees': [],
        })

    # Каждый фрагмент запроса должен совпасть хотя бы с одним полем.
    employees_query = EmployeeModel.objects.filter(work_status=True)

    # Поля, по которым выполняется поиск.
    # Для каждого слова запроса проверяется совпадение
    # хотя бы с одним из перечисленных полей.

    search_fields = (
        'last_name',
        'first_name',
        'middle_name',
        'job_title__job_title',
        'department__command_name',
        'department_group__group_dep_name',
    )

    for word in query.split():
        word_filter = Q()

        for field in search_fields:
            word_filter |= Q(**{f'{field}__icontains': word})

        employees_query = employees_query.filter(word_filter)

    employees = list(employees_query.order_by(
        'last_name',
        'first_name',
    )[:20])

    employee_ids = [employee.pk for employee in employees]

    # Отдельно получаем активные размещения найденных сотрудников.
    # Это позволяет показать, на каком этаже находится сотрудник,
    # и подготовить ссылку для перехода к нему на карте.

    placements = (
        EmployeePlacementModel.objects
        .filter(
            employee_id__in=employee_ids,
            is_active=True,
            floor_plan__is_active=True,
        )
        .select_related(
            'floor_plan__floor__building',
        )
    )

    # Создаём словарь размещений с ключом employee_id,
    # чтобы быстро находить размещение нужного сотрудника
    # при формировании результатов поиска.

    placements_by_employee = {
        placement.employee_id: placement
        for placement in placements
    }

    results = []

    for employee in employees:
        placement = placements_by_employee.get(employee.pk)

        full_name = ' '.join(filter(None, [
            employee.last_name,
            employee.first_name,
            employee.middle_name,
        ]))

        item = {
            'id': employee.pk,
            'full_name': full_name,
            'job_title': (
                employee.job_title.job_title
                if employee.job_title else ''
            ),
            'department': (
                employee.department.command_name
                if employee.department else ''
            ),
            'building': '',
            'floor': '',
            'room': '',
            'floor_url': None,
        }

        if placement:
            floor = placement.floor_plan.floor
            building = floor.building

            # Если сотрудник размещён на плане, добавляем сведения
            # о здании и этаже, а также URL для перехода к нему.
            item.update({
                'building': building.name,
                'floor': str(floor),
                'floor_url': (
                        reverse(
                            'office_map:floor_detail',
                            kwargs={'floor_id': floor.id},
                        )
                        + '?'
                        + urlencode({
                    'focus_employee': str(placement.id),
                })
                ),
            })

        # Получаем номер кабинета из дополнительной кадровой карточки.
        # Это справочная информация, она не обязательно совпадает
        # с помещением, определённым по координатам на карте.

        try:
            details = employee.moredetailsemployeemodel
            item['room'] = str(details.room or '')
        except EmployeeModel.moredetailsemployeemodel.RelatedObjectDoesNotExist:
            pass

        results.append(item)

    html = render_to_string(
        'office_map/partials/global_search_employee_results.html',
        {'employees': results},
        request=request,
    )

    return JsonResponse({
        'success': True,
        'html': html,
    })


@require_GET
def room_search(request):
    """
    Выполняет глобальный поиск помещений в выбранном здании.

    Получает поисковую строку q и ID здания building_id.
    Поиск выполняется по номеру и названию помещения.

    Для найденных помещений дополнительно ищет активные контуры,
    связанные с ними.

    Если контур найден, в результат передаётся его ID —
    он используется фронтендом для перехода к помещению на карте.

    Если помещение не имеет активного контура, оно всё равно
    попадает в результаты поиска, но без возможности перехода
    непосредственно к его контуру.

    HTML результатов формируется шаблоном
    global_search_room_results.html и возвращается в JSON.
    """

    query = request.GET.get('q', '').strip()
    building_id = request.GET.get('building_id', '').strip()

    # Для поиска необходимы минимум два символа и выбранное здание.
    # Если условия не выполнены, возвращаем пустой список результатов.

    if len(query) < 2 or not building_id:
        html = render_to_string(
            'office_map/partials/global_search_room_results.html',
            {'rooms': []},
            request=request,
        )

        return JsonResponse({
            'success': True,
            'html': html,
        })

    rooms_query = (
        RoomModel.objects
        .filter(floor__building_id=building_id)
        .select_related('floor')
    )

    # Ограничиваем поиск помещениями выбранного здания.
    # Одновременно загружаем этаж, чтобы не выполнять отдельный
    # запрос к базе для каждого найденного помещения.

    rooms_query = rooms_query.filter(
        Q(number__icontains=query)
        | Q(name__icontains=query)
    )

    rooms = list(
        rooms_query
        .order_by('floor__name', 'number')[:20]
    )

    room_ids = [room.id for room in rooms]

    # Ищем активные контуры, связанные с найденными помещениями.
    # Учитываем только контуры на активных планах этажей.

    contours = (
        RoomContourModel.objects
        .filter(
            room_id__in=room_ids,
            is_active=True,
            floor_plan__is_active=True,
        )
        .select_related('floor_plan')
    )

    # Формируем словарь контуров по ID помещения,
    # чтобы при обработке результатов быстро определить,
    # есть ли у помещения контур на карте.
    contours_by_room = {}

    for contour in contours:
        contours_by_room.setdefault(
            contour.room_id,
            contour,
        )

    results = []

    for room in rooms:
        contour = contours_by_room.get(room.id)

        results.append({
            'id': str(room.id),
            'number': str(room.number),
            'name': room.name or '',
            'floor_id': str(room.floor_id),
            'floor_name': str(room.floor),
            'contour_id': str(contour.id) if contour else None,
        })

    html = render_to_string(
        'office_map/partials/global_search_room_results.html',
        {'rooms': results},
        request=request,
    )

    return JsonResponse({
        'success': True,
        'html': html,
    })
