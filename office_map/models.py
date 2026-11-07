import datetime
import os

from django.core.exceptions import ValidationError
from uuid import UUID
from uuid_utils import uuid7

from django.conf import settings
from django.db import models

# Create your models here.
# from apps.legacy_models.models import EmployeeModel
from django.db.models import F, Q
from pathlib import PurePosixPath

from apps.legacy_models.models import EmployeeModel


def generate_uuid7():
    return UUID(str(uuid7()))

def floor_plan_upload_path(instance, filename):
    extension = PurePosixPath(filename).suffix.lower()

    return (
        f'office_map/'
        f'floors/'
        f'{instance.id}.{extension}'
    )

class BaseOfficeModel(models.Model):
    """Абстрактная базовая модель."""

    id = models.UUIDField(
        primary_key=True,
        default=generate_uuid7,
        editable=False,
    )

    created_at = models.DateTimeField(
        verbose_name="Дата создания",
        auto_now_add=True,
    )

    class Meta:
        abstract = True


class BuildingModel(BaseOfficeModel):
    name = models.CharField(
        max_length=200,
        verbose_name='Название здания'
    )
    address = models.CharField(
        max_length=300,
        blank=True,
        verbose_name='Адрес'
    )
    description = models.TextField(
        blank=True,
        verbose_name='Описание'
    )

    class Meta:
        verbose_name = 'Здание'
        verbose_name_plural = 'Здания'
        ordering = ['name']

    def __str__(self):
        return self.name


class FloorModel(BaseOfficeModel):
    building = models.ForeignKey(
        BuildingModel,
        on_delete=models.CASCADE,
        related_name='floors',
        verbose_name='Здание'
    )
    number = models.IntegerField(
        verbose_name='Номер этажа'
    )
    name = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='Название этажа'
    )

    class Meta:
        verbose_name = 'Этаж'
        verbose_name_plural = 'Этажи'
        ordering = ['building', 'number']
        constraints = [
            models.UniqueConstraint(
                fields=['building', 'number'],
                name='unique_floor_per_building'
            )
        ]

    def __str__(self):
        return f'{self.building.name} — этаж {self.number}'

class FloorPlanModel(BaseOfficeModel):
    floor = models.ForeignKey(
        FloorModel,
        on_delete=models.CASCADE,
        related_name='plans',
        verbose_name='Этаж',
    )

    source_file = models.FileField(
        upload_to=floor_plan_upload_path,
        verbose_name='Исходный файл плана',
    )

    svg_file = models.FileField(
        upload_to=floor_plan_upload_path,
        blank=True,
        verbose_name='SVG-план',
    )

    coordinate_system = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='Система координат',
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='Активный план',
    )

    class Meta:
        verbose_name = 'План этажа'
        verbose_name_plural = 'Планы этажей'
        ordering = ['-created_at']

    def __str__(self):
        return f'План: {self.floor}'

class RoomModel(BaseOfficeModel):
    floor = models.ForeignKey(
        FloorModel,
        on_delete=models.CASCADE,
        related_name='rooms',
        verbose_name='Этаж',
    )

    number = models.CharField(
        max_length=50,
        verbose_name='Номер помещения',
    )

    name = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='Название помещения',
    )

    description = models.TextField(
        blank=True,
        verbose_name='Описание',
    )

    class Meta:
        verbose_name = 'Помещение'
        verbose_name_plural = 'Помещения'
        ordering = ['floor', 'number']
        constraints = [
            models.UniqueConstraint(
                fields=['floor', 'number'],
                name='unique_room_per_floor',
            )
        ]

    def __str__(self):
        return f'{self.floor} — помещение {self.number}'

class RoomContourModel(BaseOfficeModel):
    floor_plan = models.ForeignKey(
        FloorPlanModel,
        on_delete=models.CASCADE,
        related_name='room_contours',
        verbose_name='План этажа',
    )

    room = models.ForeignKey(
        RoomModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contours',
        verbose_name='Помещение',
    )

    source_handle = models.CharField(
        max_length=20,
        verbose_name='Handle в DXF',
        null=True,
    )

    geometry = models.JSONField(
        verbose_name='Координаты контура',
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='Активен',
    )


    class Meta:
        verbose_name = 'Контур помещения'
        verbose_name_plural = 'Контуры помещений'
        constraints = [
            models.UniqueConstraint(
                fields=['floor_plan', 'source_handle'],
                name='unique_contour_handle_per_plan',
            ),
        ]

    def __str__(self):
        return f'Контур: {self.room}'



class FurnitureModel(BaseOfficeModel):
    """Тип мебели из DXF-библиотеки."""

    name = models.CharField(
        max_length=150,
        verbose_name='Название',
    )

    block_name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='Имя DXF-блока',
    )

    width_mm = models.FloatField(
        verbose_name='Ширина, мм',
    )

    height_mm = models.FloatField(
        verbose_name='Глубина, мм',
    )

    geometry = models.JSONField(
        default=list,
        verbose_name='Геометрия DXF',
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='Активна',
    )

    class Meta:
        verbose_name = 'Тип мебели'
        verbose_name_plural = 'Каталог мебели'
        ordering = ('name',)

    def __str__(self):
        return self.name


class FurniturePlacementModel(BaseOfficeModel):
    """Экземпляр мебели, размещённый на плане."""

    floor_plan = models.ForeignKey(
        FloorPlanModel,
        on_delete=models.CASCADE,
        related_name='furniture_placements',
        verbose_name='План этажа',
    )

    furniture = models.ForeignKey(
        FurnitureModel,
        on_delete=models.PROTECT,
        related_name='placements',
        verbose_name='Мебель',
    )

    x = models.FloatField(verbose_name='Координата X, мм')
    y = models.FloatField(verbose_name='Координата Y, мм')

    rotation = models.FloatField(
        default=0,
        verbose_name='Угол поворота',
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='Активна',
    )

    class Meta:
        verbose_name = 'Размещение мебели'
        verbose_name_plural = 'Расстановка мебели'
        indexes = [
            models.Index(fields=['floor_plan', 'is_active']),
        ]

    def __str__(self):
        return f'{self.furniture} — {self.floor_plan}'


class EmployeePlacementModel(BaseOfficeModel):
    employee = models.ForeignKey(
        EmployeeModel,
        on_delete=models.PROTECT,
        related_name='office_placements',
        verbose_name='Сотрудник',
        db_constraint=False,
    )

    floor_plan = models.ForeignKey(
        FloorPlanModel,
        on_delete=models.CASCADE,
        related_name='employee_placements',
        verbose_name='План этажа',
    )

    x = models.FloatField(verbose_name='Координата X, мм')
    y = models.FloatField(verbose_name='Координата Y, мм')

    is_active = models.BooleanField(default=True, verbose_name='Активно')

    class Meta:
        verbose_name = 'Размещение сотрудника'
        verbose_name_plural = 'Размещение сотрудников'
        indexes = [
            models.Index(fields=['floor_plan', 'is_active']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['employee'],
                condition=models.Q(is_active=True),
                name='unique_active_employee_placement',
            )
        ]

    def __str__(self):
        return f'{self.employee} — {self.floor_plan}'

