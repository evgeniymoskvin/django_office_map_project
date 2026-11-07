def can_edit_layout(user, building=None, floor=None):
    """
    Проверяет, может ли пользователь редактировать планировку.

    В дальнейшем здесь можно будет добавить проверку прав
    на конкретные здания и этажи.
    """
    if not user or not user.is_authenticated:
        return False

    return user.is_superuser