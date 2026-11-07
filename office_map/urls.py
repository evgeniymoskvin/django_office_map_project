from django.urls import path

from . import views

app_name = 'office_map'

urlpatterns = [
    path(
        'floors/<uuid:floor_id>/',
        views.floor_detail,
        name='floor_detail',
    ),
    path(
        'furniture/<uuid:placement_id>/move/',
        views.move_furniture,
        name='move_furniture',
    ),
    path(
        'employees/<uuid:placement_id>/move/',
        views.move_employee,
        name='move_employee',
    ),

    path(
        'rooms/contours/<uuid:contour_id>/',
        views.room_detail,
        name='room_detail',
    ),

    path('', views.map_home, name='map_home'),

    path(
        'employees/<uuid:placement_id>/',
        views.employee_detail,
        name='employee_detail',
    ),

    path(
        'furniture/<uuid:placement_id>/rotate/',
        views.rotate_furniture,
        name='rotate_furniture',
    ),
    path(
        'floors/<uuid:floor_id>/furniture/catalog/',
        views.furniture_catalog,
        name='furniture_catalog',
    ),
    path(
        'floors/<uuid:floor_id>/furniture/add/',
        views.add_furniture,
        name='add_furniture',
    ),
    path(
        'furniture/<uuid:placement_id>/delete/',
        views.delete_furniture,
        name='delete_furniture',
    ),

    path(
        'floors/<uuid:floor_id>/employees/catalog/',
        views.employee_catalog,
        name='employee_catalog',
    ),
    path(
        'floors/<uuid:floor_id>/employees/add/',
        views.add_employee,
        name='add_employee',
    ),

    path(
        'employees/<uuid:placement_id>/delete/',
        views.delete_employee,
        name='delete_employee',
    ),

    path(
        'employees/search/',
        views.employee_search,
        name='employee_search',
    ),

    path(
        'rooms/contours/<uuid:contour_id>/assign/',
        views.assign_room_to_contour,
        name='assign_room_to_contour',
    ),

    path(
        'rooms/search/',
        views.room_search,
        name='room_search',
    ),
]
