from django.contrib import admin, messages

from .services.dxf_converter import convert_dxf_to_svg
from .models import BuildingModel, FloorModel, FloorPlanModel, RoomContourModel, RoomModel, FurnitureModel, \
    FurniturePlacementModel, EmployeePlacementModel
from django.contrib import admin, messages
from office_map.services.dxf_converter import (
    convert_dxf_to_svg,
    import_room_contours,
)
from django.urls import path
from django.shortcuts import redirect, render
from django.contrib import messages

from .forms import FurnitureLibraryImportForm
from .services.furniture_importer import import_furniture_library

@admin.register(BuildingModel)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ('name', 'address', 'created_at')
    search_fields = ('name', 'address')


@admin.register(FloorModel)
class FloorAdmin(admin.ModelAdmin):
    list_display = ('building', 'number', 'name')
    list_filter = ('building',)
    search_fields = ('building__name', 'name')


@admin.register(FloorPlanModel)
class FloorPlanAdmin(admin.ModelAdmin):
    list_display = (
        'floor',
        'source_file',
        'svg_file',
        'is_active',
        'created_at',
    )

    list_filter = (
        'is_active',
        'floor__building',
    )

    search_fields = (
        'floor__building__name',
        'floor__name',
    )

    actions = [
        'convert_to_svg',
        'import_contours'
    ]

    @admin.action(description='Конвертировать DXF в SVG')
    def convert_to_svg(self, request, queryset):
        success_count = 0
        error_count = 0

        for plan in queryset:
            try:
                if not plan.source_file:
                    raise ValueError('Не загружен исходный DXF')

                convert_dxf_to_svg(plan)

                success_count += 1

            except Exception as error:
                error_count += 1
                print(
                    f'Ошибка конвертации плана {plan.id}: {error}'
                )

        if success_count:
            self.message_user(
                request,
                f'Успешно сконвертировано планов: {success_count}',
                messages.SUCCESS,
            )

        if error_count:
            self.message_user(
                request,
                f'Ошибок конвертации: {error_count}. '
                f'Подробности смотри в консоли.',
                messages.ERROR,
            )

    @admin.action(description='Импортировать контуры из DXF')
    def import_contours(self, request, queryset):
        total = 0

        for plan in queryset:
            try:
                count = import_room_contours(plan)
                total += count

            except Exception as error:
                self.message_user(
                    request,
                    f'Ошибка импорта плана {plan}: {error}',
                    level=messages.ERROR,
                )

        self.message_user(
            request,
            f'Импортировано контуров: {total}',
            level=messages.SUCCESS,
        )

@admin.register(RoomContourModel)
class RoomContourAdmin(admin.ModelAdmin):
    list_display = (
        'source_handle',
        'floor_plan',
        'room',
        'is_active',
    )

    list_editable = (
        'room',
        'is_active',
    )

    list_filter = (
        'floor_plan',
        'is_active',
    )

    search_fields = (
        'source_handle',
        'room__number',
        'room__name',
    )

    list_per_page = 50

@admin.register(RoomModel)
class RoomAdmin(admin.ModelAdmin):
    list_display = (
        'number',
        'floor',
        'name',
        'description',
    )


@admin.register(FurnitureModel)
class FurnitureAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'block_name',
        'width_mm',
        'height_mm',
        'is_active',
    )
    change_list_template = (
        'admin/office_map/furniture/change_list.html'
    )
    list_filter = ('is_active',)

    search_fields = ('name', 'block_name')

    def get_urls(self):
        urls = super().get_urls()

        custom_urls = [
            path(
                'import-library/',
                self.admin_site.admin_view(self.import_library_view),
                name='office_map_furniture_import',
            ),
        ]

        return custom_urls + urls

    def import_library_view(self, request):
        if request.method == 'POST':
            form = FurnitureLibraryImportForm(
                request.POST,
                request.FILES,
            )

            if form.is_valid():
                uploaded_file = form.cleaned_data['dxf_file']

                import tempfile
                import os

                temp_path = None

                try:
                    with tempfile.NamedTemporaryFile(
                            suffix='.dxf',
                            delete=False,
                    ) as temp_file:
                        for chunk in uploaded_file.chunks():
                            temp_file.write(chunk)

                        temp_path = temp_file.name

                    imported = import_furniture_library(temp_path)

                    messages.success(
                        request,
                        f'Успешно импортировано типов мебели: {len(imported)}',
                    )

                    return redirect('admin:office_map_furnituremodel_changelist')

                except Exception as error:
                    messages.error(
                        request,
                        f'Ошибка импорта: {error}',
                    )

                finally:
                    if temp_path and os.path.exists(temp_path):
                        os.remove(temp_path)

        else:
            form = FurnitureLibraryImportForm()

        context = {
            **self.admin_site.each_context(request),
            'title': 'Импорт библиотеки мебели',
            'form': form,
            'opts': self.model._meta,
        }

        return render(
            request,
            'admin/office_map/furniture/import_library.html',
            context,
        )


@admin.register(FurniturePlacementModel)
class FurniturePlacementAdmin(admin.ModelAdmin):
    list_display = (
        'furniture',
        'floor_plan',
        'x',
        'y',
        'rotation',
        'is_active',
    )

    list_filter = ('floor_plan', 'is_active')

@admin.register(EmployeePlacementModel)
class EmployeePlacementAdmin(admin.ModelAdmin):
    list_display = (
        'employee',
        'floor_plan',
        'x',
        'y',
        'is_active',
        'created_at',
    )

    list_filter = (
        'is_active',
        'floor_plan',
    )

    search_fields = (
        'employee__last_name',
        'employee__first_name',
        'employee__middle_name',
    )

    autocomplete_fields = (
        'employee',
        'floor_plan',
    )

    list_select_related = (
        'employee',
        'floor_plan',
    )
