"""
Сервисные функции для получения и подготовки данных сотрудников.

Модуль объединяет данные из кадровых моделей и модели размещения
сотрудников на планах этажей. Подготавливает информацию для карточек,
каталогов, поиска и SVG-маркеров.
"""

from apps.legacy_models.models import EmployeeModel
from office_map.models import EmployeePlacementModel


def get_employee_queryset():
    """
    Возвращает базовый QuerySet сотрудников с загруженными связанными данными.

    select_related используется для предварительной загрузки должности,
    подразделения, группы подразделения и дополнительных сведений,
    чтобы избежать лишних SQL-запросов при обращении к этим связям.
    """

    return (
        EmployeeModel.objects
        .select_related(
            'job_title',
            'department',
            'department_group',
            'moredetailsemployeemodel',
        )
    )


def get_employee_profile_data(employee):
    """
    Формирует словарь с основной информацией о сотруднике.

    Получает должность, подразделение, группу, телефоны, фотографию
    и дополнительные сведения из связанной модели.

    Не зависит от размещения сотрудника на плане этажа.
    Если дополнительные сведения или фотография отсутствуют,
    соответствующие поля заполняются None или пустыми значениями.
    """
    # Получаем дополнительные сведения сотрудника, если они существуют.
    try:
        details = employee.moredetailsemployeemodel
    except EmployeeModel.moredetailsemployeemodel.RelatedObjectDoesNotExist:
        details = None

    job_title = (
        employee.job_title.job_title
        if employee.job_title_id
        else ''
    )
    # Получаем название должности и подразделения с учётом отсутствующих связей.
    department = (
        employee.department.command_name
        if employee.department_id
        else ''
    )

    department_group = (
        employee.department_group.group_dep_name
        if employee.department_group_id
        else ''
    )

    # Получаем URL фотографии, если она прикреплена к дополнительным сведениям.
    photo_url = None
    if details and details.photo:
        try:
            photo_url = details.photo.url
        except ValueError:
            pass

    # Собираем единый словарь данных для дальнейшего использования в приложении.
    return {
        'id': employee.pk,
        'full_name': str(employee),
        'first_name': employee.first_name,
        'last_name': employee.last_name,
        'middle_name': employee.middle_name,
        'job_title': job_title,
        'department': department,
        'department_group': department_group,
        'phone': employee.user_phone,
        'mobile_phone': details.mobile_phone if details else None,
        'room': details.room if details else None,
        'photo_url': photo_url,
    }


def get_employee_placements(plan):
    """
    Возвращает активные размещения работающих сотрудников на указанном плане.
    Дополнительно загружает связанные данные сотрудников, чтобы при
    обработке размещений не выполнять отдельные запросы для каждой связи.
    Результат сортируется по фамилии и имени сотрудника.
    """
    # Учитываем только активные размещения работающих сотрудников на этом плане.
    # Предварительно загружаем связанные данные сотрудника.
    # Сортируем сотрудников по фамилии и имени.

    return (
        EmployeePlacementModel.objects
        .filter(
            floor_plan=plan,
            is_active=True,
            employee__work_status=True,
        )
        .select_related(
            'employee',
            'employee__job_title',
            'employee__department',
            'employee__department_group',
            'employee__moredetailsemployeemodel',
        )
        .order_by(
            'employee__last_name',
            'employee__first_name',
        )
    )


def get_employee_data(placement):
    """
    Формирует полный словарь данных сотрудника с учётом его размещения.
    Сначала получает основные данные сотрудника, затем дополняет их
    идентификатором размещения и координатами на плане этажа.
    """

    data = get_employee_profile_data(placement.employee)

    # Добавляем сведения о конкретном размещении сотрудника на плане.
    data.update({
        'placement_id': str(placement.pk),
        'x': placement.x,
        'y': placement.y,
    })

    return data


def get_available_employees():
    """
    Возвращает работающих сотрудников, у которых нет активного размещения
    ни на одном плане этажа.

    Сначала получает идентификаторы сотрудников с активными размещениями,
    затем исключает их из общего списка работающих сотрудников.

    Для каждого оставшегося сотрудника формирует словарь с данными профиля.
    """
    # Выбираем работающих сотрудников, у которых нет активного размещения.

    placed_employee_ids = (
        EmployeePlacementModel.objects
        .filter(is_active=True)
        .values_list('employee_id', flat=True)
    )

    employees = (
        get_employee_queryset()
        .filter(work_status=True)
        .exclude(pk__in=placed_employee_ids)
        .order_by('last_name', 'first_name')
    )

    # Преобразуем QuerySet в список подготовленных словарей сотрудников.
    return [
        get_employee_profile_data(employee)
        for employee in employees
    ]
