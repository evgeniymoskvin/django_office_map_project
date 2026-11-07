from django.contrib import admin

# Register your models here.
from apps.legacy_models.models import EmployeeModel, MoreDetailsEmployeeModel


class EmployeeAdmin(admin.ModelAdmin):
    # list_display = ("author", "text_task")
    ordering = ["-work_status", "last_name", "first_name", "middle_name"]
    search_fields = ["last_name", "first_name", "middle_name", "personnel_number", "user_phone"]
    list_filter = ("department_group__city_dep__city", "department_group__group_dep_abr")
    list_display = ('last_name', 'first_name', 'department')

admin.site.register(EmployeeModel, EmployeeAdmin)
admin.site.register(MoreDetailsEmployeeModel)