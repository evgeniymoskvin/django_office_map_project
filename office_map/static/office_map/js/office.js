$(document).ready(function () {
    const $viewport = $('#map-viewport');
    const $content = $('#map-content');
    const $fitButton = $('#fit-plan');
    const $resetButton = $('#reset-plan');
    const $zoomValue = $('#zoom-value');
    const $roomPanel = $('#room-panel');

    if (!$viewport.length || !$content.length) {
        return;
    }

    const viewport = $viewport[0];
    const canEditLayout = $viewport.attr('data-can-edit') === 'true';

    let scale = 1;
    let translateX = 0;
    let translateY = 0;

    let isPanning = false;
    let selectedFurniture = null;

    let objectDrag = null;
    let roomRequest = null;
    let employeeRequest = null;

    const MIN_SCALE = 0.2;
    const MAX_SCALE = 15;

    // Контекстное меню мебели
    const $furnitureContextMenu = $('#furniture-context-menu');
    let selectedFurnitureForDelete = null;

    // Контекстное меню сотрудника
    const $employeeContextMenu = $('#employee-context-menu');
    let selectedEmployeeForDelete = null;

    if (canEditLayout && $furnitureContextMenu.length) {
        $viewport.on('contextmenu', '.furniture-debug', function (event) {
            event.preventDefault();
            event.stopPropagation();

            selectedFurnitureForDelete = this;

            $furnitureContextMenu
                .css({left: event.clientX + 'px', top: event.clientY + 'px'})
                .prop('hidden', false);
        });

        // Не закрываем меню при нажатии на его содержимое.
        $(document).on('pointerdown.furnitureContextMenu', function (event) {
            if (!$(event.target).closest('#furniture-context-menu').length) {
                $furnitureContextMenu.prop('hidden', true);
            }
        });

        // Открываем меню по правому клику на сотруднике.
        $viewport.on('contextmenu', '.employee-debug', function (event) {
            event.preventDefault();
            event.stopPropagation();

            selectedEmployeeForDelete = this;

            $furnitureContextMenu.prop('hidden', true);

            $employeeContextMenu
                .css({
                    left: event.clientX + 'px',
                    top: event.clientY + 'px'
                })
                .prop('hidden', false);
        });

// Закрываем меню сотрудника при клике в другом месте.
        $(document).on('pointerdown', function (event) {
            if (!$(event.target).closest('#employee-context-menu').length) {
                $employeeContextMenu.prop('hidden', true);
            }
        });

    }

    // --------------------------------------------------
// Масштабирование и перемещение плана
// --------------------------------------------------

    function updateTransform() {
        $content.css(
            'transform',
            `translate(${translateX}px, ${translateY}px) scale(${scale})`
        );

        $zoomValue.text(`${Math.round(scale * 100)}%`);
    }

// Сброс масштаба к 100%.
    function resetView() {
        scale = 1;
        translateX = 0;
        translateY = 0;
        updateTransform();
    }

// Автоматически вписываем весь план в окно.
    function fitPlan() {
        const contentRect = $content[0].getBoundingClientRect();
        const viewportRect = viewport.getBoundingClientRect();

        if (!contentRect.width || !contentRect.height) {
            return;
        }

        const padding = 40;

        const availableWidth = viewportRect.width - padding * 2;
        const availableHeight = viewportRect.height - padding * 2;

        const fitRatio = Math.min(
            availableWidth / contentRect.width,
            availableHeight / contentRect.height
        );

        const newScale = Math.min(
            MAX_SCALE,
            Math.max(MIN_SCALE, scale * fitRatio)
        );

        const ratio = newScale / scale;

        const contentCenterX =
            contentRect.left + contentRect.width / 2 - viewportRect.left;

        const contentCenterY =
            contentRect.top + contentRect.height / 2 - viewportRect.top;

        translateX =
            viewportRect.width / 2 -
            ratio * (contentCenterX - translateX);

        translateY =
            viewportRect.height / 2 -
            ratio * (contentCenterY - translateY);

        scale = newScale;

        updateTransform();
    }

// Фокусировка на элементе плана.
    function focusOnElement(element) {
        if (!element) {
            return false;
        }

        const rect = element.getBoundingClientRect();
        const viewportRect = viewport.getBoundingClientRect();

        if (!rect.width || !rect.height) {
            return false;
        }

        const fitRatio = Math.min(
            viewportRect.width * 0.65 / rect.width,
            viewportRect.height * 0.65 / rect.height
        );

        const newScale = Math.min(
            MAX_SCALE,
            Math.max(MIN_SCALE, scale * fitRatio)
        );

        const ratio = newScale / scale;

        const elementCenterX =
            rect.left + rect.width / 2 - viewportRect.left;

        const elementCenterY =
            rect.top + rect.height / 2 - viewportRect.top;

        translateX = viewportRect.width / 2 -
            ratio * (elementCenterX - translateX);

        translateY = viewportRect.height / 2 -
            ratio * (elementCenterY - translateY);

        scale = newScale;

        updateTransform();

        return true;
    }

    function applyEmployeeFocus() {
        const placementId = $viewport.attr('data-focus-employee-id');
        const contourId = $viewport.attr('data-focus-contour-id');

        if (!placementId) {
            return;
        }

        const $employee = $content.find('.employee-debug').filter(function () {
            return this.dataset.placementId === placementId;
        });

        if (!$employee.length) {
            console.warn('Маркер сотрудника не найден:', placementId);
            return;
        }

        const $contour = contourId
            ? $content.find('.room-contour').filter(function () {
                return this.dataset.contourId === contourId;
            })
            : $();

        $content.find('.employee-focused, .room-focused')
            .removeClass('employee-focused room-focused');

        $employee.addClass('employee-focused');

        if ($contour.length) {
            $contour.addClass('room-focused');
            focusOnElement($contour[0]);
        } else {
            focusOnElement($employee[0]);
        }
    }

    function applyRoomFocus() {
        const params = new URLSearchParams(window.location.search);
        const contourId = params.get('focus_room_contour');

        if (!contourId) {
            return;
        }

        const $contour = $content.find('.room-contour').filter(function () {
            return this.dataset.contourId === contourId;
        });

        if (!$contour.length) {
            console.warn('Контур помещения после перехода не найден:', contourId);
            return;
        }

        $content.find('.room-focused').removeClass('room-focused');

        $contour.addClass('room-focused');

        focusOnElement($contour[0]);
        openRoomPanel($contour[0]);

        // Убираем параметр из адреса, чтобы при обновлении
        // страницы помещение не открывалось повторно.
        params.delete('focus_room_contour');

        const newUrl = new URL(window.location.href);
        newUrl.search = params.toString();

        window.history.replaceState({}, '', newUrl);
    }

    function zoomAt(clientX, clientY, factor) {
        const rect = viewport.getBoundingClientRect();

        const mouseX = clientX - rect.left;
        const mouseY = clientY - rect.top;

        const newScale = Math.min(
            MAX_SCALE,
            Math.max(MIN_SCALE, scale * factor)
        );

        if (newScale === scale) {
            return;
        }

        const contentX = (mouseX - translateX) / scale;
        const contentY = (mouseY - translateY) / scale;

        translateX = mouseX - contentX * newScale;
        translateY = mouseY - contentY * newScale;

        scale = newScale;

        updateTransform();
    }

    $viewport.on('wheel', function (event) {
        // Не масштабируем карту, если колесо находится
        // над панелями и каталогами.
        if (
            $(event.target).closest(
                '.room-panel, .employee-catalog-panel, .furniture-panel'
            ).length
        ) {
            return;
        }

        event.preventDefault();

        const originalEvent = event.originalEvent;

        const factor = originalEvent.deltaY < 0
            ? 1.1
            : 0.9;

        zoomAt(
            originalEvent.clientX,
            originalEvent.clientY,
            factor
        );
    });

    $fitButton.on('click', fitPlan);
    $resetButton.on('click', resetView);

    // --------------------------------------------------
    // Координаты SVG и DXF
    // --------------------------------------------------

    function getCoordinateSvg() {
        return (
            $content.find('.furniture-layer')[0] ||
            $content.find('.employee-layer')[0]
        );
    }

    function clientToSvg(clientX, clientY) {
        const svg = getCoordinateSvg();

        if (!svg) {
            return null;
        }

        const matrix = svg.getScreenCTM();

        if (!matrix) {
            return null;
        }

        const point = svg.createSVGPoint();

        point.x = clientX;
        point.y = clientY;

        return point.matrixTransform(matrix.inverse());
    }

    function getMapParameters() {
        const svg = getCoordinateSvg();

        if (!svg) {
            return null;
        }

        const minX = Number(svg.dataset.minX);
        const minY = Number(svg.dataset.minY);
        const maxX = Number(svg.dataset.maxX);
        const maxY = Number(svg.dataset.maxY);

        const viewBox = svg.viewBox.baseVal;

        const sourceWidth = maxX - minX;
        const sourceHeight = maxY - minY;

        if (
            !Number.isFinite(minX) ||
            !Number.isFinite(minY) ||
            !Number.isFinite(maxX) ||
            !Number.isFinite(maxY) ||
            !sourceWidth ||
            !sourceHeight ||
            !viewBox.width ||
            !viewBox.height
        ) {
            return null;
        }

        const mapScale = Math.min(
            viewBox.width / sourceWidth,
            viewBox.height / sourceHeight
        );

        const offsetX = (viewBox.width - sourceWidth * mapScale) / 2;
        const offsetY = (viewBox.height - sourceHeight * mapScale) / 2;

        return {
            svg,
            minX,
            minY,
            maxX,
            maxY,
            viewBox,
            mapScale,
            offsetX,
            offsetY
        };
    }

    function svgToWorld(svgX, svgY) {
        const params = getMapParameters();

        if (!params) {
            return null;
        }

        return {
            x: params.minX +
                (svgX - params.viewBox.x - params.offsetX) /
                params.mapScale,

            y: params.maxY -
                (svgY - params.viewBox.y - params.offsetY) /
                params.mapScale,

            mapScale: params.mapScale
        };
    }

    function worldToSvg(worldX, worldY) {
        const params = getMapParameters();

        if (!params) {
            return null;
        }

        return {
            x: params.viewBox.x +
                params.offsetX +
                (worldX - params.minX) * params.mapScale,

            y: params.viewBox.y +
                params.offsetY +
                (params.maxY - worldY) * params.mapScale
        };
    }

    function clientToWorld(clientX, clientY) {
        const svgPoint = clientToSvg(clientX, clientY);

        if (!svgPoint) {
            return null;
        }

        return svgToWorld(svgPoint.x, svgPoint.y);
    }

    // --------------------------------------------------
    // CSRF
    // --------------------------------------------------

    function getCookie(name) {
        const cookies = document.cookie
            ? document.cookie.split(';')
            : [];

        for (let cookie of cookies) {
            cookie = cookie.trim();

            if (cookie.startsWith(name + '=')) {
                return decodeURIComponent(
                    cookie.substring(name.length + 1)
                );
            }
        }

        return null;
    }

    // --------------------------------------------------
    // Каталог мебели
    // --------------------------------------------------

    const $furniturePanel = $('#furniture-panel');
    const $furnitureCatalog = $('#furniture-catalog-list');
    const $furnitureOpen = $('#furniture-panel-open');
    const $furnitureClose = $('#furniture-panel-close');

    // Элементы каталога сотрудников
    const $employeePanel = $('#employee-catalog-panel');
    const $employeeCatalog = $('#employee-catalog-list');
    const $employeeOpen = $('#employee-panel-open');
    const $employeeClose = $('#employee-panel-close');

    let employeeCatalogLoaded = false;
    let furnitureCatalogLoaded = false;

    function loadFurnitureCatalog() {
        const url = $viewport.attr('data-furniture-catalog-url');

        if (!url) {
            $furnitureCatalog.html('<p>Не задан URL каталога.</p>');
            return;
        }

        $furnitureCatalog.html('<p>Загрузка каталога...</p>');

        $.ajax({
            url: url,
            method: 'GET',
            dataType: 'json',

            success: function (response) {
                if (!response.success) {
                    $furnitureCatalog.html(
                        '<p>Не удалось загрузить каталог мебели.</p>'
                    );
                    return;
                }

                $furnitureCatalog.html(response.html);
                furnitureCatalogLoaded = true;
            },

            error: function (xhr) {
                console.error(
                    'Ошибка загрузки каталога мебели:',
                    xhr.responseText || xhr.statusText
                );

                $furnitureCatalog.html(
                    '<p>Не удалось загрузить каталог мебели.</p>'
                );
            }
        });
    }

    $('#furniture-search-input').on('input', function () {
        const search = $(this).val().trim().toLowerCase();

        $furnitureCatalog.find('.furniture-catalog-item').each(function () {
            const name = $(this).attr('data-furniture-name').toLowerCase();

            $(this).toggle(name.includes(search));
        });
    });

    $furnitureOpen.on('click', function () {
        $furnitureOpen.hide();
        $furniturePanel.prop('hidden', false);

        if (!furnitureCatalogLoaded) {
            loadFurnitureCatalog();
        }
    });

    $furnitureClose.on('click', function () {
        $furniturePanel.prop('hidden', true);
        $furnitureOpen.show();
    });

    // --------------------------------------------------
    // Добавление мебели на план
    // --------------------------------------------------

    let draggedFurnitureId = null;
    let draggedEmployeeId = null;

// Не передаём прокрутку каталогов обработчику масштабирования карты.
    $('#employee-catalog-panel, #furniture-panel, #furniture-catalog-list')
        .on('wheel', function (event) {
            event.stopPropagation();
        });

    $furnitureCatalog.on('dragstart', '.furniture-catalog-item', function (event) {
        if (!canEditLayout) {
            event.preventDefault();
            return;
        }

        draggedFurnitureId = this.dataset.furnitureId;

        const originalEvent = event.originalEvent;

        originalEvent.dataTransfer.setData(
            'text/plain',
            draggedFurnitureId
        );

        originalEvent.dataTransfer.effectAllowed = 'copy';

        $(this).addClass('furniture-dragging');
    });

    $furnitureCatalog.on('dragend', '.furniture-catalog-item', function () {
        draggedFurnitureId = null;
        $(this).removeClass('furniture-dragging');
    });

    // Перетаскивание сотрудника из каталога

    $employeeCatalog.on(
        'dragstart',
        '.employee-catalog-item',
        function (event) {
            if (!canEditLayout) {
                event.preventDefault();
                return;
            }

            draggedEmployeeId = this.dataset.employeeId;

            event.originalEvent.dataTransfer.setData(
                'text/plain',
                draggedEmployeeId
            );

            event.originalEvent.dataTransfer.effectAllowed = 'copy';

            $(this).addClass('employee-dragging');
        }
    );

    $employeeCatalog.on(
        'dragend',
        '.employee-catalog-item',
        function () {
            draggedEmployeeId = null;
            $(this).removeClass('employee-dragging');
        }
    );

    $viewport.on('dragover', function (event) {
        if (
            !canEditLayout ||
            (!draggedFurnitureId && !draggedEmployeeId)
        ) {
            return;
        }

        event.preventDefault();
        event.originalEvent.dataTransfer.dropEffect = 'copy';
    });

    // Удаление мебели из контекстного меню.
    // Делегирование на document надёжно работает и для динамически созданной мебели.
    $(document).on('click', '#furniture-delete-button', function (event) {
        event.preventDefault();
        event.stopPropagation();

        if (!canEditLayout || !selectedFurnitureForDelete) {
            console.warn('Не выбрана мебель для удаления или нет прав на редактирование.');
            return;
        }

        const group = selectedFurnitureForDelete;
        const placementId = group.dataset.placementId;

        if (!placementId) {
            console.error('У выбранной мебели отсутствует data-placement-id:', group);
            return;
        }

        if (!confirm('Удалить этот предмет мебели с плана?')) {
            $furnitureContextMenu.prop('hidden', true);
            return;
        }

        const urlTemplate = $viewport.attr('data-furniture-delete-url');
        if (!urlTemplate) {
            console.error('Не задан data-furniture-delete-url на #map-viewport.');
            return;
        }

        const url = urlTemplate.replace(
            '00000000-0000-0000-0000-000000000000',
            placementId
        );

        const $deleteButton = $(this).prop('disabled', true);

        $.ajax({
            url: url,
            method: 'POST',
            dataType: 'json',
            headers: {'X-CSRFToken': getCookie('csrftoken')},
            success: function (response) {
                if (!response || !response.success) {
                    alert((response && response.error) || 'Не удалось удалить мебель.');
                    return;
                }

                $(group).remove();
                if (selectedFurniture === group) {
                    selectedFurniture = null;
                }
                selectedFurnitureForDelete = null;
                $furnitureContextMenu.prop('hidden', true);
            },
            error: function (xhr) {
                console.error('Ошибка удаления мебели:', xhr.status, xhr.responseText || xhr.statusText);
                alert('Не удалось удалить мебель. Код ошибки: ' + xhr.status);
            },
            complete: function () {
                $deleteButton.prop('disabled', false);
            }
        });
    });

    $(document).on('click', '#employee-delete-button', function (event) {
        event.preventDefault();
        event.stopPropagation();

        if (!canEditLayout || !selectedEmployeeForDelete) {
            return;
        }

        const group = selectedEmployeeForDelete;
        const placementId = group.dataset.placementId;

        if (!placementId) {
            console.error('Не найден ID размещения сотрудника.');
            return;
        }

        if (!confirm('Убрать сотрудника с этого этажа?')) {
            $employeeContextMenu.prop('hidden', true);
            return;
        }

        const urlTemplate = $viewport.attr('data-employee-delete-url');

        if (!urlTemplate) {
            console.error('Не задан data-employee-delete-url.');
            return;
        }

        const url = urlTemplate.replace(
            '00000000-0000-0000-0000-000000000000',
            placementId
        );

        const $button = $(this).prop('disabled', true);

        $.ajax({
            url: url,
            method: 'POST',
            dataType: 'json',
            headers: {
                'X-CSRFToken': getCookie('csrftoken')
            },

            success: function (response) {
                if (!response || !response.success) {
                    alert(response.error || 'Не удалось убрать сотрудника.');
                    return;
                }

                $(group).remove();

                // Возвращаем сотрудника в каталог свободных.
                employeeCatalogLoaded = false;
                loadEmployeeCatalog();

                selectedEmployeeForDelete = null;
                $employeeContextMenu.prop('hidden', true);

                // Закрываем информационную панель, если она открыта.
                $roomPanel.hide().empty();
            },

            error: function (xhr) {
                console.error(
                    'Ошибка удаления сотрудника:',
                    xhr.status,
                    xhr.responseText || xhr.statusText
                );

                alert('Не удалось убрать сотрудника. Код ошибки: ' + xhr.status);
            },

            complete: function () {
                $button.prop('disabled', false);
            }
        });
    });

    $viewport.on('drop', function (event) {
        if (!canEditLayout) {
            return;
        }

        const originalEvent = event.originalEvent;
        const target = $(originalEvent.target);

        if (target.closest(
            '.furniture-panel, .employee-catalog-panel, .room-panel, ' +
            '#furniture-panel-open, #employee-panel-open'
        ).length) {
            return;
        }

        const furnitureId = draggedFurnitureId;
        const employeeId = draggedEmployeeId;

        if (!furnitureId && !employeeId) {
            return;
        }

        event.preventDefault();

        const worldPoint = clientToWorld(
            originalEvent.clientX,
            originalEvent.clientY
        );

        if (!worldPoint) {
            console.error('Не удалось определить координаты на плане.');
            return;
        }

        const params = getMapParameters();

        if (
            worldPoint.x < params.minX ||
            worldPoint.x > params.maxX ||
            worldPoint.y < params.minY ||
            worldPoint.y > params.maxY
        ) {
            console.warn('Перетащи объект в границы плана.');
            return;
        }

        if (employeeId) {
            addEmployeeToPlan(
                employeeId,
                worldPoint.x,
                worldPoint.y
            );
        } else if (furnitureId) {
            addFurnitureToPlan(
                furnitureId,
                worldPoint.x,
                worldPoint.y
            );
        }
    });

    function addFurnitureToPlan(furnitureId, x, y) {
        const url = $viewport.attr('data-furniture-add-url');

        if (!url) {
            console.error('Не задан URL добавления мебели.');
            return;
        }

        $.ajax({
            url: url,
            method: 'POST',
            contentType: 'application/json',

            headers: {
                'X-CSRFToken': getCookie('csrftoken')
            },

            data: JSON.stringify({
                furniture_id: furnitureId,
                x: x,
                y: y
            }),

            success: function (response) {
                if (!response.success || !response.furniture_svg) {
                    console.error('Сервер не вернул SVG мебели.', response);
                    return;
                }

                const parser = new DOMParser();

                const svgDocument = parser.parseFromString(
                    `<svg xmlns="http://www.w3.org/2000/svg">${response.furniture_svg}</svg>`,
                    'image/svg+xml'
                );

                if (svgDocument.querySelector('parsererror')) {
                    console.error('Ошибка разбора SVG мебели.');
                    return;
                }

                const group = svgDocument.documentElement.firstElementChild;

                if (!group || !group.classList.contains('furniture-debug')) {
                    console.error('В ответе сервера отсутствует группа мебели.');
                    return;
                }

                const furnitureLayer = $content.find('.furniture-layer')[0];

                if (!furnitureLayer) {
                    console.error('Не найден SVG-слой мебели.');
                    return;
                }

                furnitureLayer.appendChild(
                    document.importNode(group, true)
                );

                console.log('Мебель добавлена:', response.placement_id);
            },

            error: function (xhr) {
                console.error(
                    'Ошибка добавления мебели:',
                    xhr.responseText || xhr.statusText
                );
            }
        });
    }

    function addEmployeeToPlan(employeeId, x, y) {
        const url = $viewport.attr('data-employee-add-url');

        if (!url) {
            console.error('Не задан URL добавления сотрудника.');
            return;
        }

        $.ajax({
            url: url,
            method: 'POST',
            contentType: 'application/json',

            headers: {
                'X-CSRFToken': getCookie('csrftoken')
            },

            data: JSON.stringify({
                employee_id: employeeId,
                x: x,
                y: y
            }),

            success: function (response) {
                if (!response.success || !response.employee_svg) {
                    console.error(
                        'Сервер не вернул SVG сотрудника.',
                        response
                    );
                    return;
                }

                const parser = new DOMParser();

                const svgDocument = parser.parseFromString(
                    `<svg xmlns="http://www.w3.org/2000/svg">${response.employee_svg}</svg>`,
                    'image/svg+xml'
                );

                if (svgDocument.querySelector('parsererror')) {
                    console.error('Ошибка разбора SVG сотрудника.');
                    return;
                }

                const group = svgDocument.documentElement.firstElementChild;

                if (
                    !group ||
                    !group.classList.contains('employee-debug')
                ) {
                    console.error(
                        'В ответе сервера отсутствует группа сотрудника.'
                    );
                    return;
                }

                const employeeLayer = $content.find('.employee-layer')[0];

                if (!employeeLayer) {
                    console.error('Не найден SVG-слой сотрудников.');
                    return;
                }

                employeeLayer.appendChild(
                    document.importNode(group, true)
                );

                // Убираем добавленного сотрудника из каталога.
                $employeeCatalog
                    .find('.employee-catalog-item')
                    .filter(function () {
                        return this.dataset.employeeId === String(employeeId);
                    })
                    .remove();

                console.log(
                    'Сотрудник добавлен:',
                    response.placement_id
                );
            },

            error: function (xhr) {
                let message = 'Не удалось добавить сотрудника.';

                try {
                    const response = JSON.parse(xhr.responseText);

                    if (response.error) {
                        message = response.error;
                    }
                } catch (error) {
                    console.error('Не удалось разобрать ответ сервера.');
                }

                console.error(
                    'Ошибка добавления сотрудника:',
                    xhr.responseText || xhr.statusText
                );

                alert(message);
            }
        });
    }

    // --------------------------------------------------
// Каталог сотрудников
// --------------------------------------------------


    function loadEmployeeCatalog() {
        const url = $viewport.attr('data-employee-catalog-url');

        if (!url) {
            $employeeCatalog.html('<p>Не задан URL каталога сотрудников.</p>');
            return;
        }

        $employeeCatalog.html('<p>Загрузка сотрудников...</p>');

        $.ajax({
            url: url,
            method: 'GET',
            dataType: 'json',

            success: function (response) {
                if (!response.success) {
                    $employeeCatalog.html(
                        '<p>Нет свободных сотрудников для размещения.</p>'
                    );
                    employeeCatalogLoaded = true;
                    return;
                }

                $employeeCatalog.html(response.html);
                employeeCatalogLoaded = true;
            },

            error: function (xhr) {
                console.error(
                    'Ошибка загрузки каталога сотрудников:',
                    xhr.responseText || xhr.statusText
                );

                $employeeCatalog.html(
                    '<p>Не удалось загрузить каталог сотрудников.</p>'
                );
            }
        });
    }

    $employeeOpen.on('click', function () {
        $employeeOpen.hide();
        $employeePanel.prop('hidden', false);

        if (!employeeCatalogLoaded) {
            loadEmployeeCatalog();
        }
    });

    $employeeClose.on('click', function () {
        $employeePanel.prop('hidden', true);
        $employeeOpen.show();
    });

    $('#employee-search-input').on('input', function () {
        const search = $(this).val().trim().toLowerCase();

        $employeeCatalog.find('.employee-catalog-item').each(function () {
            const name = (this.dataset.employeeName || '').toLowerCase();
            const job = (this.dataset.employeeJob || '').toLowerCase();

            $(this).toggle(
                name.includes(search) || job.includes(search)
            );
        });
    });

    // --------------------------------------------------
    // Работа с помещениями
    // --------------------------------------------------


    function openEmployeePanel(group) {
        const placementId = group.dataset.placementId;

        if (!placementId) {
            return;
        }

        const urlTemplate = $viewport.attr('data-employee-detail-url');

        if (!urlTemplate) {
            console.error('Не задан data-employee-detail-url');
            return;
        }

        if (roomRequest) {
            roomRequest.abort();
            roomRequest = null;
        }

        if (employeeRequest) {
            employeeRequest.abort();
        }

        const url = urlTemplate.replace(
            '00000000-0000-0000-0000-000000000000',
            placementId
        );

        $content.find('.room-contour').removeClass('room-selected');

        $roomPanel.html(`
        <button type="button" id="close-room-panel" aria-label="Закрыть">
            ×
        </button>
        <p>Загрузка информации о сотруднике...</p>
    `).show();

        employeeRequest = $.ajax({
            url: url,
            method: 'GET',
            dataType: 'json',

            success: function (data) {
                if (!data.success) {
                    $roomPanel.html(`
                    <button type="button" id="close-room-panel">×</button>
                    <p>Не удалось загрузить информацию о сотруднике.</p>
                `);
                    return;
                }

                $roomPanel.html(data.html);
            },

            error: function (xhr, status) {
                if (status === 'abort') {
                    return;
                }

                console.error(
                    'Ошибка загрузки сотрудника:',
                    xhr.responseText || xhr.statusText
                );

                $roomPanel.html(`
                <button type="button" id="close-room-panel">×</button>
                <p>Не удалось загрузить информацию о сотруднике.</p>
            `);
            },

            complete: function () {
                employeeRequest = null;
            }
        });
    }

    $content.on('click', '.employee-debug', function (event) {
        event.preventDefault();
        event.stopPropagation();

        openEmployeePanel(this);
    });

    function closeRoomPanel() {
        $roomPanel.hide();
        $roomPanel.empty();

        $content.find('.room-contour').removeClass('room-selected');
    }

    let activeRoomContour = null;
    let currentRoomData = null;
    let roomEditMode = false;


    function openRoomPanel(contour, editMode = false) {
        const contourId = contour.dataset.contourId;

        if (employeeRequest) {
            employeeRequest.abort();
            employeeRequest = null;
        }

        if (!contourId) {
            console.error('У контура отсутствует data-contour-id');
            return;
        }

        const urlTemplate = $viewport.attr('data-room-detail-url');

        if (!urlTemplate) {
            console.error('Не задан data-room-detail-url');
            return;
        }

        const url = urlTemplate.replace(
            '00000000-0000-0000-0000-000000000000',
            contourId
        );

        if (roomRequest) {
            roomRequest.abort();
        }

        activeRoomContour = contour;
        roomEditMode = false;

        $content.find('.room-contour').removeClass('room-selected');
        $(contour).addClass('room-selected');

        $roomPanel
            .html(`
            <button type="button" id="close-room-panel" aria-label="Закрыть">×</button>
            <p>Загрузка информации...</p>
        `)
            .show();

        roomRequest = $.ajax({
            url: url,
            method: 'GET',
            dataType: 'json',
            data: {
                edit: editMode ? 1 : 0
            },
            success: function (data) {
                if (!data.success) {
                    $roomPanel.html(`
                    <button type="button" id="close-room-panel">×</button>
                    <p>Не удалось загрузить информацию о помещении.</p>
                `);
                    return;
                }

                currentRoomData = data;
                $roomPanel.html(data.html);
            },

            error: function (xhr, status) {
                if (status === 'abort') return;

                console.error(
                    'Ошибка загрузки помещения:',
                    xhr.responseText || xhr.statusText
                );

                $roomPanel.html(`
                <button type="button" id="close-room-panel">×</button>
                <p>Не удалось загрузить информацию о помещении.</p>
            `);
            },

            complete: function () {
                roomRequest = null;
            }
        });
    }

    // Клик по контуру помещения.
    $content.on('click', '.room-contour', function (event) {
        event.preventDefault();
        event.stopPropagation();

        openRoomPanel(this);
    });

    // Закрытие панели.
    $roomPanel.on('click', '#close-room-panel', function (event) {
        event.preventDefault();
        closeRoomPanel();
    });

    $roomPanel.on('click', '#room-assignment-edit', function () {
        if (!activeRoomContour) return;

        roomEditMode = true;
        openRoomPanel(activeRoomContour, true);
    });

    $roomPanel.on('click', '#room-assignment-cancel', function () {
        if (!activeRoomContour) return;

        roomEditMode = false;
        openRoomPanel(activeRoomContour, false);
    });

    $roomPanel.on('wheel', function (event) {
        event.stopPropagation();
    });

    $roomPanel.on('input', '#room-assignment-search', function () {
        const search = $(this).val().trim().toLowerCase();

        $('#room-assignment-select option').each(function () {
            if (!this.value) return;

            const text = $(this).text().toLowerCase();
            const extra = $(this).attr('data-search') || '';

            $(this).prop(
                'hidden',
                !text.includes(search) && !extra.includes(search)
            );
        });
    });

    $roomPanel.on('click', '#room-assignment-save', function () {
        const roomId = $('#room-assignment-select').val() || null;

        const urlTemplate = $viewport.attr('data-room-assign-url');

        if (!urlTemplate || !activeRoomContour) {
            console.error('Не задан URL привязки или не выбран контур.');
            return;
        }

        const contourId = activeRoomContour.dataset.contourId;

        const url = urlTemplate.replace(
            '00000000-0000-0000-0000-000000000000',
            contourId
        );

        const $button = $(this).prop('disabled', true);

        $.ajax({
            url: url,
            method: 'POST',
            contentType: 'application/json',
            dataType: 'json',

            headers: {
                'X-CSRFToken': getCookie('csrftoken')
            },

            data: JSON.stringify({
                room_id: roomId
            }),

            success: function (response) {
                if (!response.success) {
                    alert(response.error || 'Не удалось сохранить привязку.');
                    return;
                }

                roomEditMode = false;

                // Повторно загружаем карточку с актуальными данными.
                openRoomPanel(activeRoomContour);
            },

            error: function (xhr) {
                let message = 'Не удалось сохранить привязку.';

                try {
                    const response = JSON.parse(xhr.responseText);
                    message = response.error || message;
                } catch (error) {
                    console.error('Ошибка разбора ответа сервера:', error);
                }

                alert(message);
                console.error('Ошибка привязки помещения:', xhr.status, xhr.responseText);
            },

            complete: function () {
                $button.prop('disabled', false);
            }
        });
    });

    // --------------------------------------------------
    // Общие функции перетаскивания
    // --------------------------------------------------

    function startObjectDrag(event, group, type) {
        const worldPoint = clientToWorld(
            event.clientX,
            event.clientY
        );

        if (!worldPoint) {
            return;
        }

        const originalX = Number(group.dataset.x);
        const originalY = Number(group.dataset.y);

        const baseX = Number(group.dataset.baseX);
        const baseY = Number(group.dataset.baseY);

        if (
            !Number.isFinite(originalX) ||
            !Number.isFinite(originalY) ||
            !Number.isFinite(baseX) ||
            !Number.isFinite(baseY)
        ) {
            console.error(
                'Не удалось определить координаты объекта',
                group
            );
            return;
        }

        const placementId = group.dataset.placementId;

        objectDrag = {
            group,
            type,
            placementId,

            startWorldX: worldPoint.x,
            startWorldY: worldPoint.y,

            originalX,
            originalY,

            baseX,
            baseY,

            mapScale: worldPoint.mapScale,

            previousTransform: group.getAttribute('transform')
        };

        group.classList.add(`${type}-selected`);

        viewport.setPointerCapture(event.pointerId);

        event.preventDefault();
        event.stopPropagation();
    }

    function moveObject(event) {
        if (!objectDrag) {
            return;
        }

        const drag = objectDrag;

        const worldPoint = clientToWorld(
            event.clientX,
            event.clientY
        );

        if (!worldPoint) {
            return;
        }

        const deltaX = worldPoint.x - drag.startWorldX;
        const deltaY = worldPoint.y - drag.startWorldY;

        const newX = drag.originalX + deltaX;
        const newY = drag.originalY + deltaY;

        if (drag.type === 'furniture') {
            const svgDeltaX = (newX - drag.baseX) * drag.mapScale;
            const svgDeltaY = -(newY - drag.baseY) * drag.mapScale;

            drag.group.setAttribute(
                'transform',
                `translate(${svgDeltaX} ${svgDeltaY})`
            );
        }

        if (drag.type === 'employee') {
            const svgPosition = worldToSvg(newX, newY);

            if (!svgPosition) {
                return;
            }

            drag.group.setAttribute(
                'transform',
                `translate(${svgPosition.x} ${svgPosition.y})`
            );
        }

        drag.newX = newX;
        drag.newY = newY;
    }

    // --------------------------------------------------
    // Сохранение координат
    // --------------------------------------------------

    function saveObjectPosition() {
        if (!objectDrag) {
            return;
        }

        const drag = objectDrag;
        objectDrag = null;

        const group = drag.group;
        const type = drag.type;

        if (
            drag.newX === undefined ||
            drag.newY === undefined ||
            (
                Math.abs(drag.newX - drag.originalX) < 0.001 &&
                Math.abs(drag.newY - drag.originalY) < 0.001
            )
        ) {
            group.classList.remove(`${type}-selected`);
            return;
        }

        const urlAttribute = type === 'furniture'
            ? 'data-furniture-move-url'
            : 'data-employee-move-url';

        const urlTemplate = $viewport.attr(urlAttribute);

        if (!urlTemplate || !drag.placementId) {
            console.error(
                `Не задан URL или ID размещения: ${type}`
            );

            restoreObjectPosition(drag);
            return;
        }

        const moveUrl = urlTemplate.replace(
            '00000000-0000-0000-0000-000000000000',
            drag.placementId
        );

        $.ajax({
            url: moveUrl,
            method: 'POST',
            contentType: 'application/json',

            headers: {
                'X-CSRFToken': getCookie('csrftoken')
            },

            data: JSON.stringify({
                x: drag.newX,
                y: drag.newY
            }),

            success: function (response) {
                group.dataset.x = response.x;
                group.dataset.y = response.y;

                group.classList.remove(`${type}-selected`);
            },

            error: function (xhr) {
                console.error(
                    `Не удалось сохранить положение (${type}):`,
                    xhr.responseText || xhr.statusText
                );

                restoreObjectPosition(drag);
            }
        });
    }

    function restoreObjectPosition(drag) {
        const group = drag.group;

        if (drag.previousTransform) {
            group.setAttribute(
                'transform',
                drag.previousTransform
            );
        } else {
            group.removeAttribute('transform');
        }

        group.classList.remove(`${drag.type}-selected`);
    }

    // --------------------------------------------------
    // Поворот мебели
    // --------------------------------------------------

    function rotateFurniture(group, direction) {
        if (!canEditLayout || !group) {
            return;
        }

        const placementId = group.dataset.placementId;
        const urlTemplate = $viewport.attr('data-furniture-rotate-url');

        if (!placementId || !urlTemplate) {
            console.error('Не задан URL или ID размещения мебели');
            return;
        }

        const geometry = group.querySelector('.furniture-geometry');

        if (!geometry) {
            console.error('Не найдена геометрия мебели');
            return;
        }

        if (group.dataset.rotating === 'true') {
            return;
        }

        const currentRotation = Number(group.dataset.rotation || 0);
        const previousOffset = Number(group.dataset.rotationOffset || 0);

        const newRotation = (currentRotation + direction * 10 + 360) % 360;
        const newOffset = previousOffset + direction * 10;

        const anchorX = Number(group.dataset.anchorX);
        const anchorY = Number(group.dataset.anchorY);

        if (!Number.isFinite(anchorX) || !Number.isFinite(anchorY)) {
            console.error('Не определена точка вращения мебели');
            return;
        }

        const previousTransform = geometry.getAttribute('transform');

        geometry.setAttribute(
            'transform',
            `rotate(${-newOffset} ${anchorX} ${anchorY})`
        );

        group.dataset.rotating = 'true';

        const rotateUrl = urlTemplate.replace(
            '00000000-0000-0000-0000-000000000000',
            placementId
        );

        $.ajax({
            url: rotateUrl,
            method: 'POST',
            contentType: 'application/json',
            headers: {
                'X-CSRFToken': getCookie('csrftoken')
            },
            data: JSON.stringify({
                rotation: newRotation
            }),

            success: function (response) {
                group.dataset.rotation = response.rotation;
                group.dataset.rotationOffset = newOffset;
            },

            error: function (xhr) {
                console.error(
                    'Не удалось повернуть мебель:',
                    xhr.responseText || xhr.statusText
                );

                if (previousTransform) {
                    geometry.setAttribute('transform', previousTransform);
                } else {
                    geometry.removeAttribute('transform');
                }
            },

            complete: function () {
                group.dataset.rotating = 'false';
            }
        });
    }

    // --------------------------------------------------
    // Обработка указателя
    // --------------------------------------------------


    let panCandidate = null;
    const PAN_THRESHOLD = 5;

    $viewport.on('pointerdown', function (event) {
        if (event.button !== 0) {
            return;
        }

        if (
            $(event.target).closest(
                '#furniture-context-menu, #employee-context-menu, ' +
                '.room-panel, .furniture-panel, #furniture-panel-open, ' +
                '.employee-catalog-panel, #employee-panel-open'
            ).length
        ) {
            return;
        }

        const roomContour = $(event.target).closest('.room-contour')[0];

        const employeeGroup = $(event.target).closest('.employee-debug')[0];

        if (employeeGroup) {
            if (canEditLayout) {
                startObjectDrag(event, employeeGroup, 'employee');
            }
            return;
        }

        const furnitureGroup = $(event.target).closest('.furniture-debug')[0];

        if (furnitureGroup) {
            selectedFurniture = furnitureGroup;
            if (canEditLayout) {
                startObjectDrag(event, furnitureGroup, 'furniture');
            }
            return;
        }

        panCandidate = {
            pointerId: event.pointerId,
            startX: event.clientX,
            startY: event.clientY,
            initialX: translateX,
            initialY: translateY,
            roomContour: roomContour
        };
    });

    $viewport.on('pointermove', function (event) {
        if (objectDrag) {
            moveObject(event);
            return;
        }

        if (!panCandidate || panCandidate.pointerId !== event.pointerId) {
            return;
        }

        const deltaX = event.clientX - panCandidate.startX;
        const deltaY = event.clientY - panCandidate.startY;

        if (!isPanning) {
            if (Math.hypot(deltaX, deltaY) < PAN_THRESHOLD) {
                return;
            }

            isPanning = true;

            viewport.setPointerCapture(event.pointerId);
            $viewport.addClass('dragging');
        }

        translateX = panCandidate.initialX + deltaX;
        translateY = panCandidate.initialY + deltaY;

        updateTransform();
    });

    function stopPointerInteraction(event) {
        if (objectDrag) {
            saveObjectPosition();
        }

        if (isPanning) {
            isPanning = false;
            $viewport.removeClass('dragging');
        }

        panCandidate = null;

        if (
            event &&
            viewport.hasPointerCapture &&
            viewport.hasPointerCapture(event.pointerId)
        ) {
            viewport.releasePointerCapture(event.pointerId);
        }
    }

    $viewport.on('pointerup', stopPointerInteraction);
    $viewport.on('pointercancel', stopPointerInteraction);

    $viewport.on('lostpointercapture', function () {
        if (objectDrag) {
            saveObjectPosition();
        }

        isPanning = false;
        panCandidate = null;
        $viewport.removeClass('dragging');
    });


    // --------------------------------------------------
    // Управление поворотом мебели с клавиатуры
    // --------------------------------------------------

    $(document).on('keydown', function (event) {
        if (!selectedFurniture || !canEditLayout) {
            return;
        }

        // Не перехватываем клавиши при вводе текста.
        if ($(event.target).is('input, textarea, select, [contenteditable="true"]')) {
            return;
        }

        if (event.key.toLowerCase() === 'e') {
            event.preventDefault();
            rotateFurniture(selectedFurniture, 1);
        }

        if (event.key.toLowerCase() === 'q') {
            event.preventDefault();
            rotateFurniture(selectedFurniture, -1);
        }
    });


// --------------------------------------------------
// Начальное отображение плана — 100%
// --------------------------------------------------

    scale = 1;
    translateX = 0;
    translateY = 0;

    updateTransform();


    // Повторное вписывание при изменении размера окна.
    let resizeTimeout = null;

    $(window).on('resize', function () {
        clearTimeout(resizeTimeout);

        resizeTimeout = setTimeout(function () {
            fitPlan();
        }, 150);
    });


// Автоматическая фокусировка сотрудника
// при переходе из поиска или открытии встроенного плана.
    if ($viewport.attr('data-focus-employee-id')) {

        function startEmployeeFocus() {
            requestAnimationFrame(function () {
                requestAnimationFrame(function () {
                    applyEmployeeFocus();
                });
            });
        }

        const floorPlanImage = $content.find('#floor-plan')[0];

        if (floorPlanImage && !floorPlanImage.complete) {
            floorPlanImage.addEventListener(
                'load',
                startEmployeeFocus,
                {once: true}
            );
        } else {
            startEmployeeFocus();
        }
    }

    // Автоматическая фокусировка помещения
// после перехода с другого этажа.
    if (new URLSearchParams(window.location.search).has('focus_room_contour')) {

        function startRoomFocus() {
            requestAnimationFrame(function () {
                requestAnimationFrame(function () {
                    applyRoomFocus();
                });
            });
        }

        const floorPlanImage = $content.find('#floor-plan')[0];

        if (floorPlanImage && !floorPlanImage.complete) {
            floorPlanImage.addEventListener(
                'load',
                startRoomFocus,
                {once: true}
            );
        } else {
            startRoomFocus();
        }
    }

    // Навигация по зданиям и этажам.
    const $buildingSelect = $('#building-select');
    const $floorSelect = $('#floor-select');

    function filterFloors(buildingId) {
        $floorSelect.find('option').each(function () {
            const matches = this.dataset.buildingId === buildingId;
            this.hidden = !matches;
        });

        const $visibleFloors = $floorSelect.find('option').filter(function () {
            return this.dataset.buildingId === buildingId;
        });

        if ($visibleFloors.length) {
            $floorSelect.val($visibleFloors.first().val());
        }
    }

    $buildingSelect.on('change', function () {
        filterFloors(this.value);
    });

    $floorSelect.on('change', function () {
        const floorId = this.value;

        if (!floorId) return;

        const urlTemplate = $('#map-viewport').attr('data-floor-url-template');

        window.location.href = urlTemplate.replace(
            '00000000-0000-0000-0000-000000000000',
            floorId
        );
    });

// --------------------------------------------------
// Общий поиск сотрудников и помещений
// --------------------------------------------------

    const $globalEmployeeSearch = $('#global-employee-search-input');
    const $globalEmployeeResults = $('#global-employee-search-results');

    let employeeSearchTimeout = null;
    let employeeSearchRequest = null;
    let roomSearchRequest = null;
    let globalSearchVersion = 0;


// Результаты сотрудников.
// Логика перехода по floor_url сохранена.


// Общий рендеринг двух групп.
    function renderGlobalSearchResults(employeeHtml, roomHtml) {
        let html = employeeHtml + roomHtml;

        if (!html) {
            html = `
            <div class="global-search-empty">
                Ничего не найдено.
            </div>
        `;
        }

        $globalEmployeeResults.html(html).prop('hidden', false);
    }

// Поиск при вводе текста.
    $globalEmployeeSearch.on('input', function () {
        const query = this.value.trim();

        clearTimeout(employeeSearchTimeout);

        // Увеличиваем номер поиска, чтобы старые ответы
        // не перезаписывали новые результаты.
        globalSearchVersion++;
        const searchVersion = globalSearchVersion;

        if (employeeSearchRequest) {
            employeeSearchRequest.abort();
            employeeSearchRequest = null;
        }

        if (roomSearchRequest) {
            roomSearchRequest.abort();
            roomSearchRequest = null;
        }

        if (query.length < 2) {
            $globalEmployeeResults.prop('hidden', true).empty();
            return;
        }

        employeeSearchTimeout = setTimeout(function () {
            const employeeUrl = $viewport.attr('data-employee-search-url');
            const roomUrl = $viewport.attr('data-room-search-url');
            const buildingId = $viewport.attr('data-building-id');

            let employeeHtml = '';
            let roomHtml = '';
            let pending = 2;
            let hasError = false;

            function finishSearch() {
                pending--;

                if (pending !== 0 || searchVersion !== globalSearchVersion) {
                    return;
                }

                renderGlobalSearchResults(employeeHtml, roomHtml);

                if (hasError && !employeeHtml && !roomHtml) {
                    $globalEmployeeResults.html(
                        '<div class="global-search-empty">Не удалось выполнить поиск.</div>'
                    ).prop('hidden', false);
                }
            }

            employeeSearchRequest = $.ajax({
                url: employeeUrl,
                method: 'GET',
                dataType: 'json',
                data: {q: query},

                success: function (response) {
                    if (response.success) {
                        employeeHtml = response.html || '';
                    } else {
                        hasError = true;
                    }
                },

                error: function (xhr, status) {
                    if (status !== 'abort') {
                        hasError = true;
                        console.error(
                            'Ошибка поиска сотрудников:',
                            xhr.responseText || xhr.statusText
                        );
                    }
                },

                complete: function () {
                    employeeSearchRequest = null;
                    finishSearch();
                }
            });

            roomSearchRequest = $.ajax({
                url: roomUrl,
                method: 'GET',
                dataType: 'json',
                data: {
                    q: query,
                    building_id: buildingId
                },

                success: function (response) {
                    if (response.success) {
                        roomHtml = response.html || '';
                    } else {
                        hasError = true;
                    }
                },

                error: function (xhr, status) {
                    if (status !== 'abort') {
                        hasError = true;
                        console.error(
                            'Ошибка поиска помещений:',
                            xhr.responseText || xhr.statusText
                        );
                    }
                },

                complete: function () {
                    roomSearchRequest = null;
                    finishSearch();
                }
            });

        }, 300);
    });


// Выбор помещения из результатов поиска.
    $globalEmployeeResults.on(
        'click',
        '.global-search-room-result',
        function () {
            const floorId = this.dataset.roomFloorId;
            const contourId = this.dataset.roomContourId;

            if (!floorId || !contourId) {
                return;
            }

            // Если помещение находится на другом этаже —
            // переходим на него и передаём ID контура.
            if (floorId !== String($floorSelect.val())) {
                const urlTemplate = $viewport.attr('data-floor-url-template');

                if (!urlTemplate) {
                    console.error('Не задан data-floor-url-template');
                    return;
                }

                const targetUrl = urlTemplate.replace(
                    '00000000-0000-0000-0000-000000000000',
                    floorId
                );

                const url = new URL(targetUrl, window.location.origin);

                url.searchParams.set('focus_room_contour', contourId);

                window.location.href = url.toString();

                return;
            }

            // Если помещение на текущем этаже —
            // открываем его без перезагрузки страницы.
            const $contour = $content.find('.room-contour').filter(function () {
                return this.dataset.contourId === contourId;
            });

            if (!$contour.length) {
                console.warn('Контур помещения не найден:', contourId);
                return;
            }

            $content.find('.room-focused').removeClass('room-focused');

            $contour.addClass('room-focused');

            focusOnElement($contour[0]);
            openRoomPanel($contour[0]);

            $globalEmployeeResults.prop('hidden', true);
        }
    );


// Закрываем результаты при клике за пределами поиска.
    $(document).on('pointerdown', function (event) {
        if (!$(event.target).closest('.global-employee-search').length) {
            $globalEmployeeResults.prop('hidden', true);
        }
    });


// Возвращаем результаты при фокусе на поле.
    $globalEmployeeSearch.on('focus', function () {
        if (
            this.value.trim().length >= 2 &&
            $globalEmployeeResults.children().length
        ) {
            $globalEmployeeResults.prop('hidden', false);
        }
    });


// Закрываем список клавишей Escape.
    $globalEmployeeSearch.on('keydown', function (event) {
        if (event.key === 'Escape') {
            $globalEmployeeResults.prop('hidden', true);
            this.blur();
        }
    });

    $(document).on('keydown', function (event) {
        if (event.key !== 'Escape') return;

        $content.find('.employee-focused, .room-focused')
            .removeClass('employee-focused room-focused');
    });

});