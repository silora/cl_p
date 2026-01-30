import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import QtQuick.Dialogs
import QtQuick.Shapes
import QtWebEngine
import cl_p

ApplicationWindow {
    id: window
    flags: Qt.FramelessWindowHint | Qt.Popup | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint

    width: appConfig.ui && appConfig.ui.window && appConfig.ui.window.width ? appConfig.ui.window.width : 620
    height: appConfig.ui && appConfig.ui.window && appConfig.ui.window.height ? appConfig.ui.window.height : 860
    visible: false
    color: "transparent"
    title: qsTr("cl_p")
    onActiveChanged: if (!active && visible) backend.hideWindow()
    onVisibleChanged: if (visible) Qt.callLater(function() { window.raise(); window.requestActivate(); focusCatcher.forceActiveFocus(); })

    property bool searchBarVisible: false

    function focusPopup() {
        focusCatcher.forceActiveFocus()
    }

    function toggleSearchBar() {
        window.searchBarVisible = !window.searchBarVisible
        if (window.searchBarVisible) {
            Qt.callLater(function() { searchField.forceActiveFocus(); searchField.selectAll(); })
        } else {
            Qt.callLater(function() { focusCatcher.forceActiveFocus(); })
        }
    }

    FocusScope {
        id: focusCatcher
        anchors.fill: parent
        focus: true
        Keys.onPressed: (e) => {
            if (e.modifiers & Qt.ControlModifier && e.key === Qt.Key_F) {
                e.accepted = true
                window.toggleSearchBar()
                return
            }
            if (e.key === Qt.Key_Escape) {
                e.accepted = true
                backend.hideWindow()
            }
        }
    }

    Shortcut {
        sequences: [ StandardKey.Find ]
        context: Qt.ApplicationShortcut
        onActivated: window.toggleSearchBar()
    }

    // define global color palette (overridable via config.yaml)
    property var grays: paletteGrays || ["#212529", "#343a40", "#495057", "#6c757d", "#adb5bd", "#ced4da", "#dee2e6", "#e9ecef", "#f8f9fa"]
    property var lightColors: paletteLightColors || ["#F94144", "#F9C74F", "#90BE6D", "#54a4ea", "#D1A2E6", "#F3722C", "#43AA8B", "#277DA1", "#F8961E", "#F9844A", "#4D908E"]
    property var darkColors: paletteDarkColors || ["#C73335", "#C9A23F", "#739957", "#427eaf", "#9a78a9", "#C15A22", "#35876F", "#1F6481", "#C77618", "#C66A3C", "#3D7371"]
    property var highlightColors: paletteHighlightColors || ["#ff6565", "#ededed", "#68a8fc"]

    property int selectedClipId: -1
    property string iconsRoot: Qt.resolvedUrl("../icons/")

    property bool autoScrollAfterRefresh: true
    property int  savedAnchorId: -1
    property real savedAnchorOffset: 0
    property bool pendingScrollRestore: false
    property int _restoreTries: 0

    WebEngineProfile {
        id: pluginProfile
        persistentCookiesPolicy: WebEngineProfile.NoPersistentCookies
        httpCacheType: WebEngineProfile.MemoryHttpCache
    }

    function addAlphaToColor(hexColor, alpha) {
        if (!hexColor || typeof hexColor !== "string") return hexColor;
        var m = /^#([A-Fa-f0-9]{6})$/.exec(hexColor);
        if (!m) {
            m = /^#([A-Fa-f0-9]{8})$/.exec(hexColor);
            if (m) {
                hexColor = "#" + hexColor.slice(3);
            } else {
                return hexColor;
            }
        }
        var a = Math.round(Math.min(Math.max(alpha, 0), 1) * 255);
        var alphaHex = a.toString(16).padStart(2, "0");
        return "#" + alphaHex + hexColor.slice(1);
    }

    function mixColor(a, b) {
        function hexToRgb(hex) {
            var m = /^#([A-Fa-f0-9]{6})$/.exec(hex);
            var offset = 1;
            if (!m) {
                m = /^#([A-Fa-f0-9]{8})$/.exec(hex);
                if (m) offset = 3;
                else return null;
            }
            return {
                r: parseInt(hex.slice(offset, offset + 2), 16),
                g: parseInt(hex.slice(offset + 2, offset + 4), 16),
                b: parseInt(hex.slice(offset + 4, offset + 6), 16)
            };
        }
        var rgbA = hexToRgb(a);
        var rgbB = hexToRgb(b);
        if (!rgbA || !rgbB) return a;
        var r = Math.round((rgbA.r + rgbB.r) / 2);
        var g = Math.round((rgbA.g + rgbB.g) / 2);
        var b = Math.round((rgbA.b + rgbB.b) / 2);
        return "#" + r.toString(16).padStart(2, "0")
                   + g.toString(16).padStart(2, "0")
                   + b.toString(16).padStart(2, "0");
    }

    function snapshotScrollForDelegate(clipId, delegateY) {
        if (!clipList) return
        savedAnchorId = clipId
        savedAnchorOffset = delegateY - clipList.contentY
        pendingScrollRestore = true
        _restoreTries = 0
        console.log("Snapshot scroll for clip", clipId, "offset", savedAnchorOffset, "contentY", clipList.contentY)
    }

    function _resolveAnchorIndex() {
        if (!clipModel || savedAnchorId < 0) return -1
        if (clipModel.indexOfId) return clipModel.indexOfId(savedAnchorId)
        if (clipModel.rowForId) return clipModel.rowForId(savedAnchorId)
        if (clipModel.count !== undefined && clipModel.idAt) {
            for (var i = 0; i < clipModel.count; ++i) {
                if (clipModel.idAt(i) === savedAnchorId) return i
            }
        }
        return -1
    }

    function restoreScrollWhenStable() {
        if (!clipList || !pendingScrollRestore) return

        var idx = _resolveAnchorIndex()
        if (idx < 0) {
            pendingScrollRestore = false
            savedAnchorId = -1
            savedAnchorOffset = 0
            return
        }

        clipList.positionViewAtIndex(idx, ListView.Beginning)

        Qt.callLater(function() {
            var target = clipList.contentY - savedAnchorOffset
            var maxY = Math.max(0, clipList.contentHeight - clipList.height)
            target = Math.max(0, Math.min(maxY, target))
            clipList.contentY = target

            Qt.callLater(function() {
                if (!pendingScrollRestore) return
                _restoreTries += 1
                if (_restoreTries >= 6) {
                    pendingScrollRestore = false
                    savedAnchorId = -1
                    savedAnchorOffset = 0
                    return
                }
                restoreScrollWhenStable()
            })
        })
    }

    Shortcut {
        sequences: ["Ctrl+Enter"]
        enabled: window.selectedClipId > 0
        onActivated: backend.activateItem(window.selectedClipId, true)
    }
    Shortcut {
        sequences: ["Alt+V"]
        onActivated: backend.toggleWindow()
    }
    Shortcut {
        sequences: ["Escape"]
        onActivated: backend.hideWindow()
    }

        // ===========================
        // Round-edge root container
        // ===========================
        Rectangle {
            id: rootFrame
            anchors.fill: parent
            radius: 16
            color: grays[0]
            clip: true
            antialiasing: true

        // optional: dragging window by empty header area (你也可以只给 header 某块加)
        // MouseArea {
        //     anchors.fill: headerBar
        //     acceptedButtons: Qt.LeftButton
        //     onPressed: window.startSystemMove()
        // }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 10

            // ===========================
            // Group bar
            // ===========================
            Rectangle {
                id: groupBar
                radius: 12
                Layout.fillWidth: true
                Layout.preferredHeight: 46
                color: grays[0]
                gradient: Gradient {
                    GradientStop { position: 0.0; color: grays[2] }
                    GradientStop { position: 1.0; color: grays[1] }
                }
                border.width: 0

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 3
                    spacing: 4

                    ListView {
                        id: groupList
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        orientation: ListView.Horizontal
                        spacing: 8
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds

                        model: groupModel
                        flickDeceleration: 5000
                        maximumFlickVelocity: 20000
                        ScrollBar.horizontal: ScrollBar {
                            policy: ScrollBar.AsNeeded
                        }

                        delegate: Item {
                            id: tabRoot
                            height: groupList.height
                            width: tabPill.implicitWidth

                            property int gid: model.id
                            property bool isSpecial: model.isSpecial
                            property bool isPlugin: model.isPlugin
                            property bool checked: backend.currentGroupId === gid
                            property bool isDestination: backend.destinationGroupId === gid
                            property bool hovered: false
                            property bool pressed: false
                            property real dragOffset: 0
                            property int dropIndexGuess: -1
                            property bool dragging: false
                            property real lastDragTranslation: 0

                            z: dragging ? 2 : 0
                            transform: Translate { x: tabRoot.dragOffset }

                            function dropIndex(handler) {
                                var total = groupList.count || (groupModel ? groupModel.count : 0)
                                if (total === undefined || total <= 0) return -1
                                var tx = handler && handler.translation ? (handler.translation.x || tabRoot.lastDragTranslation || 0)
                                                                        : tabRoot.lastDragTranslation
                                var localCenter = Qt.point(tabRoot.width / 2, tabRoot.height / 2)
                                var pLocal = Qt.point(localCenter.x + tx, localCenter.y)
                                var p = tabRoot.mapToItem(groupList.contentItem, pLocal.x, pLocal.y)
                                var idx = groupList.indexAt(p.x, groupList.height / 2)
                                if (idx < 0 && p.x > 0) idx = total - 1
                                if (idx < 0 && p.x <= 0) idx = 2
                                var specialCount = (groupModel && groupModel.specialCount) ? groupModel.specialCount() : 2
                                var minUser = total > specialCount ? specialCount : Math.max(0, total - 1)
                                if (idx < minUser) idx = minUser
                                if (idx > total - 1) idx = total - 1
                                return idx
                            }

                                Rectangle {
                                    id: tabPill
                                    anchors.verticalCenter: parent.verticalCenter
                                    height: parent.height - 2
                                    radius: 8

                                    implicitWidth: tabRoot.isSpecial
                                               ? height
                                               : Math.max(56, (label.visible ? label.implicitWidth : 0) + (tabIcon.visible ? tabIcon.width + 8 : 0) + 24)

                                    color: (tabRoot.isDestination ? ((tabRoot.checked || tabRoot.hovered) ? highlightColors[0] : mixColor(highlightColors[0], grays[0])) : ((tabRoot.checked || tabRoot.hovered) ? grays[0] : grays[2]))
                                    border.width: tabRoot.checked ? 3 : 0
                                    border.color: grays[3]

                                RowLayout {
                                    id: tabRow
                                    anchors.fill: parent
                                    anchors.leftMargin: tabRoot.isSpecial ? 6 : 12
                                    anchors.rightMargin: tabRoot.isSpecial ? 6 : 8
                                    spacing: tabRoot.isSpecial ? 6 : 4

                                    Image {
                                        id: tabIcon
                                        visible: tabRoot.isSpecial
                                        source: tabRoot.isPlugin ? iconsRoot + "icon_colored.png"
                                                : (tabRoot.gid < 0 ? iconsRoot + "icon_full.png" : iconsRoot + "icon.png")
                                        sourceSize.width: 24
                                        sourceSize.height: 24
                                        width: 18
                                        height: 18
                                        fillMode: Image.PreserveAspectFit
                                        Layout.alignment: Qt.AlignHCenter | Qt.AlignVCenter
                                        Layout.fillWidth: false
                                        ToolTip.visible: hovered && tabRoot.isSpecial
                                        ToolTip.text: tabRoot.isSpecial
                                                      ? (tabRoot.isPlugin
                                                         ? qsTr("Plugins")
                                                         : (tabRoot.gid < 0 ? qsTr("All Clips") : qsTr("Default Group")))
                                                      : ""
                                    }

                                    Label {
                                        id: label
                                        text: model.name
                                        color: grays[8]
                                        font.pixelSize: 18
                                        font.weight: tabRoot.checked ? Font.DemiBold : Font.Medium
                                        elide: Text.ElideRight
                                        visible: !tabRoot.isSpecial && !tabRoot.isPlugin
                                        Layout.alignment: Qt.AlignVCenter
                                        Layout.maximumWidth: 220
                                        Layout.preferredWidth: visible ? implicitWidth : 0
                                        Layout.minimumWidth: visible ? 0 : 0
                                    }
                                }

                                DragHandler {
                                    id: dragGroup
                                    enabled: !tabRoot.isSpecial
                                    xAxis.enabled: true
                                    yAxis.enabled: false
                                    target: null
                                    grabPermissions: PointerHandler.TakeOverForbidden

                                    onActiveChanged: {
                                        tabRoot.dragging = active
                                        if (!active) {
                                            var targetIndex = tabRoot.dropIndex(dragGroup)
                                            var total = groupList.count || (groupModel ? groupModel.count : 0)
                                            if (index < 0 || index >= total) {
                                                console.log("group drag release ignored (source out of range)", "index", index, "total", total)
                                            } else if (targetIndex < 0 || targetIndex >= total) {
                                                console.log("group drag release ignored (target out of range)", "target", targetIndex, "total", total)
                                            } else if (targetIndex !== index) {
                                                console.log("group drag release reorder", "from", index, "to", targetIndex, "total", total)
                                                backend.reorderGroups(index, targetIndex)
                                            } else {
                                                console.log("group drag no reorder", "index", index, "target", targetIndex)
                                            }
                                            tabRoot.dragOffset = 0
                                            tabRoot.lastDragTranslation = 0
                                            tabRoot.dropIndexGuess = -1
                                        }
                                    }
                                    onTranslationChanged: {
                                        tabRoot.dragOffset = translation.x
                                        tabRoot.dropIndexGuess = tabRoot.dropIndex(dragGroup)
                                        tabRoot.lastDragTranslation = translation.x
                                    }
                                }

                                TapHandler {
                                    acceptedButtons: Qt.LeftButton
                                    onTapped: backend.selectGroup(tabRoot.gid)
                                    onDoubleTapped: backend.setDestinationGroup(tabRoot.gid)
                                }

                                TapHandler {
                                    acceptedButtons: Qt.RightButton
                                    gesturePolicy: TapHandler.ReleaseWithinBounds
                                    onTapped: function(ev) {
                                        if (tabRoot.gid < 0) return
                                        var canSend = tabRoot.gid !== backend.destinationGroupId
                                        var canEdit = !tabRoot.isSpecial
                                        if (!(canSend || canEdit)) return
                                        var pos = ev && ev.position ? ev.position : Qt.point(0, 0)
                                        var p = tabRoot.mapToItem(Overlay.overlay, pos.x, pos.y)
                                        groupTabMenu.x = p.x
                                        groupTabMenu.y = p.y
                                        groupTabMenu.open()
                                    }
                                }

                                HoverHandler { onHoveredChanged: tabRoot.hovered = hovered }

                                TapHandler {
                                    acceptedButtons: Qt.LeftButton
                                    gesturePolicy: TapHandler.DragThreshold
                                    onPressedChanged: tabRoot.pressed = pressed
                                }
                            }

                            Menu {
                                id: groupTabMenu
                                parent: window.contentItem
                                Component.onCompleted: {
                                    if (Overlay.overlay) parent = Overlay.overlay
                                    close()
                                }
                                padding: 2
                                implicitWidth: 110
                                modal: false
                                closePolicy: Popup.CloseOnPressOutside | Popup.CloseOnEscape

                                background: Rectangle {
                                    radius: 10
                                    color: grays[0]
                                    border.color: grays[3]
                                    border.width: 2
                                }

                                component GroupMenuItem: MenuItem {
                                    id: gmi
                                    height: visible ? implicitHeight : 0
                                    hoverEnabled: true
                                    font.pixelSize: 14
                                    leftPadding: 10
                                    rightPadding: 10
                                    topPadding: 4
                                    bottomPadding: 4
                                    padding: 0
                                    background: Rectangle {
                                        anchors.fill: parent
                                        radius: 8
                                        color: gmi.hovered ? grays[2] : "transparent"
                                        border.width: 0
                                    }
                                    contentItem: Label {
                                        text: gmi.text
                                        color: grays[8]
                                        font.pixelSize: gmi.font.pixelSize
                                        elide: Text.ElideRight
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                }

                                GroupMenuItem {
                                    id: sendHereItem
                                    visible: tabRoot.gid !== backend.destinationGroupId
                                    text: qsTr("Send here")
                                    enabled: tabRoot.gid >= 0
                                    onTriggered: backend.setDestinationGroup(tabRoot.gid)
                                }

                                GroupMenuItem {
                                    id: renameGroupItem
                                    text: qsTr("Rename")
                                    visible: !tabRoot.isSpecial
                                    onTriggered: groupDialog.openForRename(tabRoot.gid, model.name)
                                }
                                GroupMenuItem {
                                    id: deleteGroupItem
                                    text: qsTr("Delete")
                                    visible: !tabRoot.isSpecial
                                    onTriggered: confirmDeleteGroup(tabRoot.gid, model.name)
                                }
                            }
                        }
                    }

                    ToolButton {
                        id: addGroupBtn
                        focusPolicy: Qt.NoFocus
                        hoverEnabled: true

                        implicitWidth: 38
                        implicitHeight: 38

                        contentItem: Label {
                            text: "+"
                            font.pixelSize: 30
                            color: grays[6]
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }

                        background: Rectangle {
                            radius: 10
                            color: (addGroupBtn.hovered || addGroupBtn.pressed) ? grays[0] : grays[2]
                            border.width: 0
                        }

                        onClicked: groupDialog.openForCreate()
                    }
                }
            }

            // ===========================
            // Header (moved inside rootFrame)
            // ===========================
            ToolBar {
                id: headerBar
                visible: window.searchBarVisible
                Layout.fillWidth: true
                Layout.preferredHeight: 30
                background: Rectangle { 
                    color: "transparent"
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 3
                    spacing: 10

                    RowLayout {
                        id: searchRow
                        Layout.fillWidth: true
                        spacing: 8
                        property int pinFilterMode: 0  // 0=all,1=pinned,2=unpinned

                        TextField {
                            id: searchField
                            Layout.fillWidth: true
                            placeholderText: qsTr("Search clips...")
                            color: grays[8]
                            font.pixelSize: 16
                            background: Rectangle {
                                radius: 10
                                color: grays[1]
                                border.color: grays[3]
                                border.width: 2
                            }
                            onTextChanged: searchDebounce.restart()
                        }

                        ToolButton {
                            id: regexToggle
                            text: ".*"
                            checkable: true
                            checked: false
                            font.pixelSize: 14
                            background: Rectangle {
                                radius: 10
                                color: regexToggle.checked
                                       ? grays[2]
                                       : (regexToggle.hovered || regexToggle.pressed ? grays[1] : grays[0])
                                border.color: grays[3]
                                border.width: 2
                            }
                            onToggled: searchDebounce.restart()
                        }

                        ToolButton {
                            id: matchCaseToggle
                            text: qsTr("Aa")
                            checkable: true
                            checked: false
                            font.pixelSize: 14
                            background: Rectangle {
                                radius: 10
                                color: matchCaseToggle.checked
                                       ? grays[2]
                                       : (matchCaseToggle.hovered || matchCaseToggle.pressed ? grays[1] : grays[0])
                                border.color: grays[3]
                                border.width: 2
                            }
                            onToggled: searchDebounce.restart()
                        }

                        ToolButton {
                            id: pinFilterToggle
                            icon.source: iconsRoot + (searchRow.pinFilterMode === 2 ? "unpinned.png" : "pinned.png")
                            icon.width: 18
                            icon.height: 18
                            icon.color: grays[8] // invert the dark icon to match the dark background
                            background: Rectangle {
                                radius: 10
                                color: searchRow.pinFilterMode === 0
                                       ? (pinFilterToggle.hovered || pinFilterToggle.pressed ? grays[1] : grays[0])
                                       : grays[2]
                                border.color: grays[3]
                                border.width: 2
                            }
                            ToolTip.visible: hovered
                            ToolTip.text: searchRow.pinFilterMode === 0
                                           ? qsTr("All clips")
                                           : (searchRow.pinFilterMode === 1 ? qsTr("Pinned only") : qsTr("Unpinned only"))
                            onClicked: {
                                searchRow.pinFilterMode = (searchRow.pinFilterMode + 1) % 3
                                searchDebounce.restart()
                            }
                        }

                        ComboBox {
                            id: filterCombo
                            Layout.preferredWidth: 140
                            Layout.preferredHeight: searchField.implicitHeight
                            font.pixelSize: 14
                            model: [
                                qsTr("All"),
                                qsTr("Raw text"),
                                qsTr("Rich text"),
                                qsTr("URL"),
                                qsTr("Color"),
                                qsTr("Image"),
                                qsTr("Vector")
                            ]
                            background: Rectangle {
                                radius: 10
                                color: grays[0]
                                border.color: grays[3]
                                border.width: 2
                            }
                            contentItem: Text {
                                text: filterCombo.displayText
                                font: filterCombo.font
                                color: grays[8]
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: 10
                                rightPadding: 10
                                elide: Text.ElideRight
                            }
                            delegate: ItemDelegate {
                                width: filterCombo.width
                                text: modelData
                                leftPadding: 10
                                rightPadding: 10
                                topPadding: 4
                                bottomPadding: 4
                                background: Rectangle {
                                    radius: 8
                                    color: hovered ? grays[2] : "transparent"
                                    border.width: 0
                                }
                                contentItem: Text {
                                    text: modelData
                                    color: grays[8]
                                    font.pixelSize: 14
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                }
                            }
                            popup: Popup {
                                y: filterCombo.height
                                width: filterCombo.width
                                height: contentItem.implicitHeight + 4
                                padding: 2
                                background: Rectangle {
                                    radius: 10
                                    color: grays[0]
                                    border.color: grays[3]
                                    border.width: 2
                                }
                                contentItem: ListView {
                                    implicitHeight: contentHeight
                                    model: filterCombo.delegateModel
                                    currentIndex: filterCombo.highlightedIndex
                                    clip: true
                                    ScrollIndicator.vertical: ScrollIndicator { }
                                }
                            }
                            onCurrentIndexChanged: searchDebounce.restart()
                        }
                    }

                    Timer {
                        id: searchDebounce
                        interval: 250
                        repeat: false
                        onTriggered: backend.setSearch(
                                         searchField.text,
                                         regexToggle.checked,
                                         !matchCaseToggle.checked,
                                         filterCombo.currentIndex,
                                         searchRow.pinFilterMode)
                    }
                }
            }

            // ===========================
            // Main list container
            // ===========================
            Rectangle {
                id: listContainer
                radius: 12
                color: grays[1]
                gradient: Gradient {
                    GradientStop { position: 0.0; color: backend.pluginsGroupId === backend.currentGroupId ? mixColor(highlightColors[0], grays[1]) : grays[1] }
                    GradientStop { position: 1.0; color: backend.pluginsGroupId === backend.currentGroupId ? mixColor(highlightColors[2], grays[3]) : grays[3] }
                }
                border.color: "transparent"
                Layout.fillWidth: true
                Layout.fillHeight: true

                ListView {
                    id: clipList
                    anchors.fill: parent
                    anchors.margins: 8
                    property bool dragLocked: false
                    property var rootWindow: window
                    interactive: !dragLocked
                    model: clipModel
                    spacing: 12
                    clip: true
                    maximumFlickVelocity: 5000
                    flickDeceleration: 1500
                    // Preload more delegates offscreen to reduce visible popping during fast scroll.
                    cacheBuffer: Math.max(0, height * 3)
                    onContentHeightChanged: window.restoreScrollWhenStable()
                    onCountChanged: {
                        if (currentIndex >= count) {
                            currentIndex = -1
                            window.selectedClipId = -1
                        }
                        window.restoreScrollWhenStable()
                    }
                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AsNeeded
                        implicitWidth: 12
                        minimumSize: 0.1
                        anchors.right: parent.right
                        anchors.rightMargin: 0
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                    }

                    Connections {
                        target: backend
                        function onCurrentGroupChanged() {
                            clipList.currentIndex = -1
                            window.selectedClipId = -1
                        }
                    }

                    delegate: ItemDelegate {
                        id: delegateRoot
                        width: ListView.view.width
                        hoverEnabled: true
                        padding: 0
                        background: Item {}

                        property int clipId: model.id
                        property bool clipHasFull: model.hasFullContent
                        property bool expanded: false
                        property bool longPressActive: false
                        property bool isCurrent: delegateRoot.ListView.isCurrentItem
                        property bool isPinned: model.pinned
                        property bool isHovered: pressArea.containsMouse || openBadge.hovered || actionHover.hovered
                        // Provide access to the parent ListView inside the delegate scope
                        readonly property var clipList: ListView.view

                        property string clipContentType: model.contentType
                        property bool isImageContent: clipContentType === "image" || clipContentType === "svg+xml" || clipContentType === "drawio"
                        property bool isDrawio: clipContentType === "drawio"
                        property bool isTextContent: !isImageContent && clipContentType !== "color"
                        property string imageFormat: isImageContent
                                                    ? (clipContentType === "svg+xml"
                                                       ? "SVG"
                                                       : (clipContentType === "drawio" ? "DRAWIO" : "PNG"))
                                                    : ""
                        property string clipContentText: model.contentText
                        property string clipContentBlob: model.contentBlob
                        property string clipPreviewText: model.previewText
                        property int clipContentLength: model.contentLength
                        property string clipBaseColor: model.baseColor
                        property string clipLabel: model.label
                        property string clipTooltip: model.tooltip
                        property string previewSource: model.preview
                        property string clipRenderMode: model.renderMode
                        property string clipPluginId: model.pluginId
                        property var clipExtraActions: model.extraActions || []
                        property var subitemsData: model.subitems ? model.subitems : []
                        property bool longPressHoverPan: false
                        property int clipGroupId: model.groupId
                        property bool isPluginItem: clipGroupId === backend.pluginsGroupId
                        property bool longByLength: clipContentLength > 400

                        onExpandedChanged: {
                            if (delegateRoot.expanded && !delegateRoot.clipHasFull) {
                                backend.loadItemContent(delegateRoot.clipId)
                            }
                        }

                        readonly property int pluginCollapsedH: model.collapsedHeight > 0 ? model.collapsedHeight : 300
                        readonly property int pluginExpandedH: model.expandedHeight > 0 ? model.expandedHeight : 300
                        readonly property int textCollapsedH: isPluginItem ? pluginCollapsedH : 150
                        readonly property int textExpandedH: isPluginItem ? pluginExpandedH : 400
                        readonly property int imgCollapsedH: 200
                        readonly property int imgMaxExpandedH: 800

                        property real richNaturalH: rich ? rich.naturalHeight : 0
                        property bool richIsLong: rich ? rich.isLong : (richNaturalH > textCollapsedH || longByLength)
                        property int clipCharCount: delegateRoot.clipContentLength

                        function contentPanelInnerWidth() { return Math.max(0, contentPanel.width - 16) }

                        function invertColor(hex) {
                            if (!hex || typeof hex !== "string") return "#000000";
                            var m = /^#([A-Fa-f0-9]{6})$/.exec(hex);
                            var a = "";
                            if (!m) {
                                m = /^#([A-Fa-f0-9]{8})$/.exec(hex);
                                if (m) { a = hex.slice(1, 3); hex = "#" + hex.slice(3); }
                            }
                            if (!m) return "#000000";
                            var h = m[1];
                            var r = 255 - parseInt(h.slice(0, 2), 16);
                            var g = 255 - parseInt(h.slice(2, 4), 16);
                            var b = 255 - parseInt(h.slice(4, 6), 16);
                            var inv = "#" + r.toString(16).padStart(2, "0")
                                         + g.toString(16).padStart(2, "0")
                                         + b.toString(16).padStart(2, "0");
                            return a ? "#" + a + inv.slice(1) : inv;
                        }

                        function cardGradientStops() {
                            var base = delegateRoot.clipBaseColor ? delegateRoot.clipBaseColor : highlightColors[1]
                            if (delegateRoot.isPinned && !delegateRoot.isCurrent) {
                                return { s0: delegateRoot.isHovered ? highlightColors[0] : highlightColors[1],
                                         s35: delegateRoot.isHovered ? highlightColors[1] : highlightColors[2],
                                         s75: highlightColors[2], s1: highlightColors[2] }
                            }
                            if (delegateRoot.isPinned && delegateRoot.isCurrent) {
                                return { s0: highlightColors[0], s35: highlightColors[0], s75: highlightColors[1], s1: highlightColors[2] }
                            }
                            if (delegateRoot.isCurrent) {
                                return { s0: highlightColors[0], s35: addAlphaToColor(highlightColors[0], 0.5), s75: addAlphaToColor(base, 0.5), s1: addAlphaToColor(base, 0.5) }
                            }
                            return { s0: delegateRoot.isHovered ? highlightColors[0] : base, s35: addAlphaToColor(base, 0.5), s75: base, s1: addAlphaToColor(base, 0.5) }
                        }

                        property color gs0: highlightColors[1]
                        property color gs35: highlightColors[1]
                        property color gs75: highlightColors[1]
                        property color gs1: highlightColors[1]
                        property real gs75Pos: 0.75

                        function applyGradientStops() {
                            var s = cardGradientStops()
                            gs0 = s.s0
                            gs35 = s.s35
                            gs75 = s.s75
                            gs1 = s.s1
                        }
                        function requestGradientUpdate() { gradUpdate.restart() }
                        onIsPinnedChanged: requestGradientUpdate()
                        onIsCurrentChanged: {
                            requestGradientUpdate()
                            if (!delegateRoot.isCurrent) {
                                delegateRoot.gs75Pos = 0.75
                            }
                        }
                        onIsHoveredChanged: requestGradientUpdate()
                        onClipBaseColorChanged: requestGradientUpdate()
                        Component.onCompleted: applyGradientStops()

                        // Behavior on gs0  { ColorAnimation { duration: 140 } }
                        // Behavior on gs35 { ColorAnimation { duration: 140 } }
                        // Behavior on gs75 { ColorAnimation { duration: 140 } }
                        // Behavior on gs1  { ColorAnimation { duration: 140 } }

                        function subIcon(tag) {
                            var t = (tag || "").toLowerCase()
                            if (t === "ocr") return "ocr.png"
                            if (t === "translate") return "translate.png"
                            if (t === "improve") return "improve.png"
                            if (t === "summarize") return "summarize.png"
                            if (t === "format") return "format.png"
                            if (t === "note") return "note.png"
                            if (t === "file") return "file.png"
                            return "open.png"
                        }

                        implicitHeight: mainContent.implicitHeight + 14
                        height: implicitHeight

                        function endLongPress() {
                            if (!delegateRoot.longPressActive) return
                            delegateRoot.longPressActive = false
                            delegateRoot.expanded = false
                            delegateRoot.longPressHoverPan = false
                            clipList.dragLocked = false
                            rich.endPointer()
                        }

                        // function copyColorFromWeb(actionId) {
                        //     if (delegateRoot.clipPluginId !== "colorpicker") return
                        //     var view = pluginViewLoader ? pluginViewLoader.item : null
                        //     if (!view || typeof view.runJavaScript !== "function") return
                        //     var script = "(function(){ const hx=document.getElementById('hex'); return hx?hx.textContent.trim():''; })();"
                        //     view.runJavaScript(script, function(res) {
                        //         if (res) {
                        //             backend.pluginSetBaseColor(delegateRoot.clipPluginId, res)
                        //         }
                        //         backend.pluginAction(delegateRoot.clipPluginId, actionId)
                        //     })
                        // }

                        contentItem: Item {
                            anchors.fill: parent
                            // anchors.leftMargin: delegateRoot.isPluginItem ? 16 : 0
                            // anchors.rightMargin: delegateRoot.isPluginItem ? 16 : 0

                            Timer {
                                id: gradUpdate
                                interval: 0
                                repeat: false
                                onTriggered: delegateRoot.applyGradientStops()
                            }

                            SequentialAnimation {
                                id: selectSweep
                                running: delegateRoot.isCurrent
                                loops: Animation.Infinite
                                onStopped: delegateRoot.gs75Pos = 0.75

                                NumberAnimation {
                                    target: delegateRoot
                                    property: "gs75Pos"
                                    from: 0.45
                                    to: 0.9
                                    duration: 3000
                                    easing.type: Easing.InOutSine
                                }
                                NumberAnimation {
                                    target: delegateRoot
                                    property: "gs75Pos"
                                    from: 0.9
                                    to: 0.45
                                    duration: 3000
                                    easing.type: Easing.InOutSine
                                }
                            }

                            Shape {
                                id: card
                                anchors.fill: parent
                                z: 0
                                layer.enabled: height <= 2000
                                layer.samples: 8
                                layer.smooth: height <= 2000
                                antialiasing: true

                                ShapePath {
                                    strokeWidth: 0

                                    fillGradient: LinearGradient {
                                        x1: 0; y1: 0
                                        x2: card.width * 1/3;
                                        y2: card.width * 1/3;

                                        GradientStop { position: 0.0;  color: delegateRoot.gs0 }
                                        GradientStop { position: 0.35; color: delegateRoot.gs35 }
                                        GradientStop {
                                            id: gs75Stop
                                            position: delegateRoot.gs75Pos
                                            color: delegateRoot.gs75
                                        }
                                        GradientStop { position: 1.0;  color: delegateRoot.gs1 }
                                    }

                                    PathRectangle {
                                        x: 0; y: 0
                                        width: card.width
                                        height: card.height
                                        radius: 16
                                    }
                                }
                            }

                            Rectangle {
                                id: mainContent
                                anchors.fill: card
                                anchors.margins: delegateRoot.isPluginItem ? 0 : 6
                                radius: 12
                                color: delegateRoot.clipBaseColor !== "" ? delegateRoot.clipBaseColor : grays[6]
                                implicitHeight: mainContentCol.implicitHeight

                                ColumnLayout {
                                    id: mainContentCol
                                    anchors.fill: parent
                                    spacing: 0
                                    z: 0

                                    Rectangle {
                                        id: contentPanel
                                        Layout.fillWidth: true
                                        radius: 12
                                        color: delegateRoot.clipBaseColor !== "" ? delegateRoot.clipBaseColor : grays[6]
                                        clip: true

                                        implicitHeight: {
                                            if (delegateRoot.isImageContent) {
                                                var h = imgLoader.item ? imgLoader.item.targetHeight : delegateRoot.imgCollapsedH
                                                return h + 16
                                            }
                                            if (delegateRoot.clipContentType === "color") return contentCol.implicitHeight + 16
                                            return contentCol.implicitHeight + 16
                                        }
                                        height: implicitHeight

                                        ColumnLayout {
                                            id: contentCol
                                            anchors.fill: parent
                                            anchors.margins: 8
                                            spacing: 6
                                            clip: true

                                            SuperRichText {
                                                id: rich
                                                Layout.fillWidth: true
                                                Layout.preferredWidth: Math.max(1, contentPanel.width - 16)
                                                Layout.minimumWidth: 1
                                                Layout.preferredHeight: Math.max(1, capHeight)
                                                Layout.minimumHeight: 1
                                                stripClasses: delegateRoot.clipGroupId === backend.pluginsGroupId ? ["sound", "pron-gs", "oxford3000"] : []
                                                // skipNormalize: delegateRoot.clipGroupId === backend.pluginsGroupId

                                                property real naturalH: Math.max(24, (naturalHeight || 0))
                                                property bool isLong: naturalH > delegateRoot.textCollapsedH
                                                property real capHeight: isLong
                                                        ? (delegateRoot.expanded
                                                               ? Math.min(naturalH, delegateRoot.textExpandedH)
                                                               : Math.min(naturalH, delegateRoot.textCollapsedH))
                                                        : naturalH

                                                wrapAnywhere: true
                                                wordWrap: true
                                                fontPointSize: 9

                                                Binding { target: rich; property: "collapsed"; value: !delegateRoot.expanded }
                                                onWidthChanged: refreshLayout()

                                                hoverPanEnabled: (delegateRoot.isHovered || delegateRoot.longPressHoverPan) && !clipList.flicking && !clipList.moving
                                                skipNormalize: true
                                                color: delegateRoot.clipBaseColor !== "" ? delegateRoot.clipBaseColor : grays[6]
                                                textColor: grays[2]

                                                fullText: (delegateRoot.clipContentType === "html" || delegateRoot.clipContentType === "color") ? "" : delegateRoot.clipContentText
                                                collapsedText: (delegateRoot.clipContentType === "html" || delegateRoot.clipContentType === "color") ? "" : backend.truncateText(delegateRoot.clipContentText, 800)
                                                fullHtml: (delegateRoot.clipContentType === "html" || delegateRoot.clipContentType === "color") ? delegateRoot.clipContentBlob : ""
                                                collapsedHtml: (delegateRoot.clipContentType === "html" || delegateRoot.clipContentType === "color") ? backend.truncateHtml(delegateRoot.clipContentBlob, 800) : ""

                                                visible: (!delegateRoot.isPluginItem && !delegateRoot.isImageContent)
                                                         || (delegateRoot.isPluginItem && delegateRoot.clipRenderMode === "rich")
                                            }

                                            Loader {
                                                id: pluginViewLoader
                                                Layout.fillWidth: true
                                                Layout.preferredWidth: Math.max(1, contentPanel.width - 16)
                                                Layout.minimumWidth: 1
                                                Layout.preferredHeight: active ? (delegateRoot.expanded ? delegateRoot.textExpandedH : delegateRoot.textCollapsedH) : 0
                                                Layout.minimumHeight: active ? Layout.preferredHeight : 0
                                                visible: active
                                                active: delegateRoot.isPluginItem && delegateRoot.clipRenderMode !== "rich"
                                                sourceComponent: Component {
                                                    WebEngineView {
                                                        id: pluginView
                                                        anchors.fill: parent
                                                        backgroundColor: delegateRoot.clipBaseColor !== "" ? delegateRoot.clipBaseColor : grays[6]
                                                        property string htmlSource: delegateRoot.clipContentBlob
                                                        profile: pluginProfile

                                                        function reloadHtml() {
                                                            if (delegateRoot.isPluginItem && htmlSource && visible) {
                                                                loadHtml(htmlSource, "about:blank")
                                                            }
                                                        }

                                                        Component.onCompleted: reloadHtml()
                                                        onHtmlSourceChanged: reloadHtml()
                                                        onVisibleChanged: {
                                                            if (!visible) {
                                                                // Cancel in-flight renders when leaving the plugins tab to avoid WebEngine crashes.
                                                                stop();
                                                                loadHtml("", "about:blank");
                                                            } else {
                                                                reloadHtml();
                                                            }
                                                        }
                                                        onWidthChanged: reloadHtml()
                                                        Component.onDestruction: stop()
                                                        // WheelHandler {
                                                        //     id: pluginWheelPassthrough
                                                        //     target: null
                                                        //     acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                                                        //     onWheel: function(event) { console.log(event); event.accepted = false }
                                                        // }
                                                    }
                                                }
                                            }

                                            // Label {
                                            //     id: colorRect
                                            //     Layout.fillWidth: true
                                            //     visible: delegateRoot.clipContentType === "color"
                                            //     text: delegateRoot.clipBaseColor
                                            //     horizontalAlignment: Qt.AlignHCenter
                                            //     verticalAlignment: Qt.AlignVCenter
                                            //     font.pixelSize: 18
                                            //     color: (0.299*parseInt(delegateRoot.clipBaseColor.slice(1,3),16) + 0.587*parseInt(delegateRoot.clipBaseColor.slice(3,5),16) + 0.114*parseInt(delegateRoot.clipBaseColor.slice(5,7),16)) > 128 ? "#000" : "#fff"
                                            //     height: 100
                                            // background: Rectangle {
                                            //     anchors.fill: parent
                                            //     color: delegateRoot.clipBaseColor !== "" ? delegateRoot.clipBaseColor : grays[6]
                                            //     border.width: 0
                                            //     radius: 8
                                            // }

                                            Loader {
                                                id: imgLoader
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: imgLoader.item ? imgLoader.item.targetHeight : delegateRoot.imgCollapsedH
                                                Layout.minimumHeight: imgLoader.item ? imgLoader.item.targetHeight : delegateRoot.imgCollapsedH
                                                active: delegateRoot.isImageContent
                                                asynchronous: false
                                                visible: active
                                                sourceComponent: imageContent
                                            }

                                            Component {
                                                id: imageContent
                                                Item {
                                                    id: imgContainer
                                                    anchors.fill: parent
                                                    property real targetHeight: delegateRoot.imgCollapsedH

                                                    function recalcTargetHeight() {
                                                        var w = (img.implicitWidth > 0
                                                                  ? img.implicitWidth
                                                                  : (img.sourceSize.width > 0 ? img.sourceSize.width : 1));
                                                        var h = (img.implicitHeight > 0
                                                                  ? img.implicitHeight
                                                                  : (img.sourceSize.height > 0 ? img.sourceSize.height : 1));
                                                        var aspect = w > 0 ? h / w : 1.0;
                                                        var expandedH = Math.max(delegateRoot.imgCollapsedH,
                                                                                 Math.min(delegateRoot.imgMaxExpandedH,
                                                                                          aspect * Math.max(0, contentPanel.width - 16)));
                                                        targetHeight = delegateRoot.expanded ? expandedH : delegateRoot.imgCollapsedH;
                                                        if (delegateRoot.clipContentType === "svg+xml" && img.source !== "") {
                                                            var sw = Math.max(1, contentPanel.width - 16);
                                                            var sh = Math.max(1, targetHeight);
                                                            img.sourceSize = Qt.size(sw, sh);
                                                        } else if (img.sourceSize.width > 0 || img.sourceSize.height > 0) {
                                                            img.sourceSize = Qt.size(0, 0); // reset for raster types
                                                        }
                                                    }

                                                    implicitHeight: targetHeight
                                                    height: targetHeight
                                                    Component.onCompleted: recalcTargetHeight()
                                                    onWidthChanged: recalcTargetHeight()
                                                    Connections {
                                                        target: delegateRoot
                                                        function onExpandedChanged() { imgContainer.recalcTargetHeight(); }
                                                    }
                                                    Connections {
                                                        target: contentPanel
                                                        function onWidthChanged() { imgContainer.recalcTargetHeight(); }
                                                    }

                                                    Image {
                                                        id: img
                                                        anchors.horizontalCenter: parent.horizontalCenter
                                                        anchors.verticalCenter: parent.verticalCenter
                                                        source: delegateRoot.isImageContent && delegateRoot.previewSource !== ""
                                                            ? delegateRoot.previewSource
                                                            : ""
                                                        fillMode: Image.PreserveAspectFit
                                                        asynchronous: true
                                                        cache: true
                                                        width: parent.width
                                                        height: imgContainer.targetHeight
                                                        onStatusChanged: imgContainer.recalcTargetHeight()
                                                        onSourceChanged: {
                                                            if (status === Image.Ready || status === Image.Loading) {
                                                                imgContainer.recalcTargetHeight()
                                                            }
                                                        }
                                                    }

                                                    Rectangle {
                                                        id: formatTag
                                                        visible: delegateRoot.imageFormat !== ""
                                                        anchors.left: parent.left
                                                        anchors.bottom: parent.bottom
                                                        anchors.margins: 0
                                                        radius: 6
                                                        color: addAlphaToColor(grays[3], 0.9)
                                                        border.width: 0
                                                        height: formatText.implicitHeight + 6
                                                        width: formatText.implicitWidth + 12
                                                        opacity: 0.9

                                                        Text {
                                                            id: formatText
                                                            anchors.centerIn: parent
                                                            text: delegateRoot.imageFormat
                                                            color: grays[8]
                                                            font.pixelSize: 16
                                                            font.bold: true
                                                            font.capitalization: Font.AllUppercase
                                                        }
                                                    }
                                                }
                                            }
                                        }

                                        MouseArea {
                                            id: pressArea
                                            anchors.fill: contentPanel
                                            acceptedButtons: delegateRoot.isPluginItem && delegateRoot.clipRenderMode === "web"
                                                              ? Qt.RightButton    // let left clicks fall through to WebEngineView
                                                              : (Qt.LeftButton | Qt.RightButton)
                                            hoverEnabled: true
                                            preventStealing: delegateRoot.longPressActive
                                            propagateComposedEvents: true
                                            z: 0

                                            onClicked: function(mouse) {
                                                if (delegateRoot.isPluginItem && delegateRoot.clipRenderMode === "web") {
                                                    mouse.accepted = false
                                                    return
                                                }
                                                clipList.currentIndex = index
                                                clipList.rootWindow.selectedClipId = delegateRoot.clipId
                                            }
                                            onDoubleClicked: function(mouse) {
                                                if (delegateRoot.isPluginItem && delegateRoot.clipRenderMode === "web") {
                                                    mouse.accepted = false
                                                    return
                                                }
                                                clipList.currentIndex = index
                                                clipList.rootWindow.selectedClipId = delegateRoot.clipId
                                                var t = delegateRoot.clipContentText || ""
                                                // var isUrl = /^\s*(https?:\/\/|www\.)/i.test(t)
                                                // if (isUrl) {
                                                //     Qt.openUrlExternally(t)
                                                //     return
                                                // }
                                                backend.activateItem(delegateRoot.clipId, true)
                                                clipList.rootWindow.visible = false
                                            }
                                            onPressAndHold: {
                                                clipList.currentIndex = index
                                                clipList.rootWindow.selectedClipId = delegateRoot.clipId
                                                var canExpand = delegateRoot.isImageContent || delegateRoot.richIsLong
                                                if (!canExpand) return
                                                delegateRoot.longPressActive = true
                                                delegateRoot.expanded = true
                                                clipList.dragLocked = true
                                                if (delegateRoot.isTextContent) {
                                                    delegateRoot.longPressHoverPan = true
                                                    rich.feedPointer(Qt.point(mouseX, mouseY))
                                                }
                                            }
                                            onPositionChanged: function(mouse) {
                                                if (delegateRoot.longPressActive && delegateRoot.isTextContent) {
                                                    rich.feedPointer(Qt.point(mouse.x, mouse.y))
                                                mouse.accepted = true
                                                }
                                            }
                                            onWheel: function(wheel) {
                                                clipList.dragLocked = false
                                                wheel.accepted = false
                                            }
                                            onReleased: delegateRoot.endLongPress()
                                            onCanceled: delegateRoot.endLongPress()

                                            onPressed: function(mouse) {
                                                if (mouse.button === Qt.RightButton) {
                                                    var p = pressArea.mapToItem(Overlay.overlay, mouse.x, mouse.y)
                                                    contextMenu.x = p.x
                                                    contextMenu.y = p.y
                                                    contextMenu.popup()
                                                    mouse.accepted = true
                                                }
                                            }
                                        }

                                        Rectangle {
                                            id: textCountTag
                                            visible: delegateRoot.isTextContent && delegateRoot.richIsLong && !isPluginItem
                                            anchors.left: contentPanel.left
                                            anchors.bottom: contentPanel.bottom
                                            anchors.margins: 8
                                            radius: 6
                                            color: addAlphaToColor(grays[3], 0.9)
                                            border.width: 0
                                            height: countText.implicitHeight + 6
                                            width: countText.implicitWidth + 12
                                            opacity: 0.9

                                            Text {
                                                id: countText
                                                anchors.centerIn: parent
                                                text: delegateRoot.clipCharCount + " chars"
                                                color: grays[8]
                                                font.pixelSize: 16
                                                font.bold: true
                                            }
                                        }
                                    }

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2
                                        visible: subitemsData && subitemsData.length > 0
                                        Layout.preferredHeight: visible ? implicitHeight : 0
                                        Layout.minimumHeight: 0
                                        Layout.maximumHeight: visible ? implicitHeight : 0

                                        Repeater {
                                            model: subitemsData

                                            delegate: Rectangle {
                                                id: subitemCard
                                                Layout.fillWidth: true
                                                Layout.margins: 5
                                            Layout.topMargin: 0
                                            radius: 10
                                            color: grays[5]
                                            border.width: 2
                                            border.color: grays[4]
                                            // Ensure row keeps its implicit height after margins (8 top/bottom).
                                            implicitHeight: row.implicitHeight + 8
                                            clip: true

                                            RowLayout {
                                                id: row
                                                anchors.fill: parent
                                                    anchors.margins: 2
                                                    anchors.leftMargin: 6
                                                    anchors.rightMargin: 6
                                                    spacing: 4

                                                    Rectangle {
                                                        width: 20
                                                        height: 20
                                                        radius: 6
                                                        color: "transparent"
                                                        border.width: 0
                                                        Layout.alignment: Qt.AlignVCenter

                                                        Image {
                                                            anchors.centerIn: parent
                                                            source: iconsRoot + delegateRoot.subIcon(modelData.tag)
                                                            width: 18
                                                            height: 18
                                                            sourceSize.width: 18
                                                            sourceSize.height: 18
                                                            fillMode: Image.PreserveAspectFit
                                                        }
                                                    }

                                                    Text {
                                                        id: subitemText
                                                        Layout.fillWidth: true
                                                        Layout.alignment: Qt.AlignVCenter
                                                        text: modelData && modelData.text ? String(modelData.text) : ""
                                                        textFormat: Text.PlainText
                                                        wrapMode: Text.Wrap
                                                        maximumLineCount: 4
                                                        color: grays[2]
                                                        font.pixelSize: 13

                                                        lineHeightMode: Text.FixedHeight
                                                        lineHeight: Math.ceil(font.pixelSize * 1.2)

                                                        readonly property int maxHeight: lineHeight * maximumLineCount
                                                        Layout.preferredHeight: Math.min(paintedHeight, maxHeight)
                                                        Layout.maximumHeight: maxHeight
                                                        clip: true
                                                    }
                                                }

                                                MouseArea {
                                                    anchors.fill: subitemCard
                                                    hoverEnabled: true
                                                    cursorShape: Qt.PointingHandCursor
                                                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                                                    ToolTip.visible: containsMouse
                                                    ToolTip.delay: 700
                                                    ToolTip.text: modelData && modelData.text ? "[" + String(modelData.tag) + "] " + String(modelData.text) : ""
                                                    onDoubleClicked: {
                                                        var t = modelData && modelData.text ? String(modelData.text) : ""
                                                        var tag = modelData && modelData.tag ? String(modelData.tag).toLowerCase() : ""
                                                        if (!t) return
                                                        if (tag === "file") {
                                                            backend.openFilePath(t)
                                                            clipList.rootWindow.visible = false
                                                            return
                                                        }
                                                        var isUrl = /^\s*(https?:\/\/|www\.)/i.test(t)
                                                        if (isUrl) {
                                                            Qt.openUrlExternally(t)
                                                            return
                                                        }
                                                        backend.activateSubitem(delegateRoot.clipId, t, true)
                                                        clipList.rootWindow.visible = false
                                                    }
                                                    onPressAndHold: function(mouse) {
                                                        var t2 = modelData && modelData.text ? String(modelData.text) : ""
                                                        if (!mouse || mouse.button === Qt.LeftButton) {
                                                            if (t2) backend.promoteSubitem(delegateRoot.clipId, t2)
                                                        } else if (mouse.button === Qt.RightButton) {
                                                            if (modelData && modelData.id !== undefined) {
                                                                backend.deleteSubitem(delegateRoot.clipId, modelData.id)
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }

                                Menu {
                                    id: contextMenu
                                    parent: window.contentItem
                                    Component.onCompleted: {
                                        if (Overlay.overlay) parent = Overlay.overlay
                                        close()
                                    }
                                    padding: 2
                                    topPadding: 10
                                    bottomPadding: 10
                                    implicitWidth: 230
                                    cascade: true
                                background: Rectangle {
                                    radius: 10
                                    color: grays[0]
                                    border.color: grays[3]
                                    border.width: 2
                                }
                                property bool hasImageAction: delegateRoot.clipContentType === "image"
                                property bool hasHtmlAction: delegateRoot.clipContentType === "html"
                                property bool hasDrawioAction: delegateRoot.clipContentType === "drawio"
                                property bool hasSvgPngAction: delegateRoot.clipContentType === "svg+xml" || delegateRoot.clipContentType === "drawio"
                                property bool hasColorAction: delegateRoot.clipContentType === "color"
                                property bool hasPluginActions: isPluginItem && normalizedPluginActions(delegateRoot.clipExtraActions).length > 0
                                property bool hasOptionalAction: hasImageAction || hasHtmlAction || hasSvgPngAction || hasColorAction || hasPluginActions
                                onAboutToShow: {
                                    moveToMenu.targets = backend.moveTargetsForItem(delegateRoot.clipId) || []
                                }
                                onClosed: {
                                    if (moveToMenu.visible) moveToMenu.close()
                                }
                                component StyledMenuItem: MenuItem {
                                    id: smi
                                    hoverEnabled: true
                                    font.pixelSize: 16
                                    property int baseLeftPadding: 10
                                    property int baseRightPadding: 10
                                    property int baseTopPadding: 4
                                    property int baseBottomPadding: 4
                                    property int basePadding: 0

                                    leftPadding: baseLeftPadding
                                    rightPadding: baseRightPadding
                                    topPadding: visible ? baseTopPadding : 0
                                    bottomPadding: visible ? baseBottomPadding : 0
                                    padding: visible ? basePadding : 0

                                    height: visible ? implicitHeight : 0

                                    background: Rectangle {
                                        anchors.fill: parent
                                        anchors.leftMargin: 6
                                        anchors.rightMargin: 6
                                        radius: 8
                                        color: smi.hovered ? grays[2] : "transparent"
                                        border.width: 0
                                    }

                                    contentItem: Label {
                                        text: smi.text
                                        color: grays[8]
                                        font.pixelSize: smi.font.pixelSize
                                        elide: Text.ElideRight
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                }

                                delegate: StyledMenuItem {
                                    id: menuItemDelegate
                                    font.pixelSize: 14
                                    property string displayText: (model && model.text !== undefined)
                                                                  ? model.text
                                                                  : ((model && model.title !== undefined)
                                                                        ? model.title
                                                                        : (text !== undefined ? text : ""))
                                    text: displayText
                                    visible: model && model.visible !== undefined ? model.visible : true
                                }
                                    Component { id: pluginActionItemComponent; StyledMenuItem {
                                            property var row
                                            font.pixelSize: 16
                                            text: row && row.text ? row.text : ""
                                            onTriggered: {
                                                if (delegateRoot.isPluginItem && delegateRoot.clipRenderMode === "web") {
                                                    var view = pluginViewLoader ? pluginViewLoader.item : null
                                                    if (view && typeof view.runJavaScript === "function") {
                                                        view.runJavaScript("(window.cl_pPayload && window.cl_pPayload()) || null", function(res) {
                                                            backend.pluginActionWithPayload(delegateRoot.clipPluginId, row.id, res)
                                                        })
                                                    } else {
                                                        backend.pluginActionWithPayload(delegateRoot.clipPluginId, row.id, null)
                                                    }
                                                } else {
                                                    backend.pluginAction(delegateRoot.clipPluginId, row.id)
                                                }
                                                if (contextMenu && contextMenu.visible) contextMenu.close()
                                                if (moveToMenu && moveToMenu.visible) moveToMenu.close()
                                            }
                                        } }
                                    Component { id: pluginActionSeparatorComponent; MenuSeparator {} }
                                    function normalizedPluginActions(raw) {
                                        var out = []
                                        var lastSep = true
                                        var arr = raw || []
                                        for (var i = 0; i < arr.length; i++) {
                                            var row = arr[i] || {}
                                            var isSep = (row.separator === true) || (row.type === "separator")
                                            if (isSep) {
                                                if (lastSep) continue
                                                lastSep = true
                                                out.push(row)
                                            } else {
                                                lastSep = false
                                                out.push(row)
                                            }
                                        }
                                        if (out.length > 0) {
                                            var tail = out[out.length - 1]
                                            var tailSep = (tail.separator === true) || (tail.type === "separator")
                                            if (tailSep) out.pop()
                                        }
                                        return out
                                    }
                                    StyledMenuItem {
                                        text: delegateRoot.isPinned ? qsTr("Unpin") : qsTr("Pin")
                                        font.pixelSize: 16
                                        visible: !isPluginItem
                                        onTriggered: backend.togglePin(delegateRoot.clipId)
                                    }
                                    StyledMenuItem {
                                        text: qsTr("Delete")
                                        font.pixelSize: 16
                                        visible: !isPluginItem
                                        onTriggered: backend.deleteItem(delegateRoot.clipId)
                                    }
                                    MenuSeparator {
                                        visible: contextMenu.hasOptionalAction && !isPluginItem
                                        height: visible ? implicitHeight : 0
                                        topPadding: visible ? 6 : 0
                                        bottomPadding: visible ? 6 : 0
                                    }
                                    Repeater {
                                        model: isPluginItem ? contextMenu.normalizedPluginActions(delegateRoot.clipExtraActions) : []
                                        delegate: Loader {
                                            property var row: modelData
                                            sourceComponent: (row && (row.separator === true || row.type === "separator")) ? pluginActionSeparatorComponent : pluginActionItemComponent
                                            onLoaded: {
                                                if (item && item.hasOwnProperty("row")) {
                                                    item.row = row
                                                }
                                            }
                                        }
                                    }
                                    // MenuSeparator {
                                    //     visible: isPluginItem && contextMenu.hasPluginActions
                                    //     height: visible ? implicitHeight : 0
                                    //     topPadding: visible ? 6 : 0
                                    //     bottomPadding: visible ? 6 : 0
                                    // }
                                    StyledMenuItem {
                                        font.pixelSize: 16
                                        visible: contextMenu.hasImageAction
                                        text: qsTr("Paste scaled image")
                                        onTriggered: backend.copyScaledImage(delegateRoot.clipId)
                                    }
                                    StyledMenuItem {
                                        font.pixelSize: 16
                                        visible: contextMenu.hasColorAction
                                        text: qsTr("Paste as HEX")
                                        onTriggered: backend.pasteColor(delegateRoot.clipId, "hex")
                                    }
                                    StyledMenuItem {
                                        font.pixelSize: 16
                                        visible: contextMenu.hasColorAction
                                        text: qsTr("Paste as RGB")
                                        onTriggered: backend.pasteColor(delegateRoot.clipId, "rgb")
                                    }
                                    StyledMenuItem {
                                        font.pixelSize: 16
                                        visible: contextMenu.hasColorAction
                                        text: qsTr("Paste as HSL")
                                        onTriggered: backend.pasteColor(delegateRoot.clipId, "hsl")
                                    }
                                    StyledMenuItem {
                                        font.pixelSize: 16
                                        visible: contextMenu.hasHtmlAction && !isPluginItem
                                        text: qsTr("Paste as text")
                                        onTriggered: {
                                            backend.pasteHtmlAsText(delegateRoot.clipId)
                                        }
                                    }
                                    StyledMenuItem {
                                        font.pixelSize: 16
                                        visible: contextMenu.hasHtmlAction && !isPluginItem
                                        text: qsTr("Paste as raw HTML")
                                        onTriggered: {
                                            backend.pasteHtmlRaw(delegateRoot.clipId)
                                        }
                                    }
                                    StyledMenuItem {
                                        font.pixelSize: 16
                                        visible: contextMenu.hasDrawioAction
                                        text: qsTr("Paste as SVG")
                                        onTriggered: backend.pasteDrawio(delegateRoot.clipId)
                                    }
                                    StyledMenuItem {
                                        font.pixelSize: 16
                                        visible: contextMenu.hasSvgPngAction
                                        text: qsTr("Paste as PNG")
                                        onTriggered: backend.pasteVectorPng(delegateRoot.clipId)
                                    }
                                    MenuSeparator {
                                        visible: (contextMenu.hasOptionalAction || delegateRoot.clipContentType === "text") && !isPluginItem
                                        height: visible ? implicitHeight : 0
                                        topPadding: visible ? 6 : 0
                                        bottomPadding: visible ? 6 : 0
                                    }
                                    StyledMenuItem {
                                        id: moveToOpener
                                        visible: !isPluginItem
                                        text: qsTr("Move to")
                                        font.pixelSize: 16
                                        enabled: moveToMenu.targets && moveToMenu.targets.length > 0

                                        function openSubmenu() {
                                            if (!enabled) return
                                            if (moveToMenu.visible || moveToMenu.isOpening) return
                                            moveToCloseTimer.stop()
                                            moveToMenu.isOpening = true
                                            var spacing = 4
                                            var ctxWidth = contextMenu.width > 0 ? contextMenu.width : (contextMenu.implicitWidth || 230)
                                            var submenuWidth = moveToMenu.implicitWidth > 0 ? moveToMenu.implicitWidth : (moveToMenu.width || 200)
                                            var placeRight = (window.width - (contextMenu.x + ctxWidth)) >= submenuWidth + spacing
                                            var targetX = placeRight ? (contextMenu.x + ctxWidth + spacing) : Math.max(0, contextMenu.x - submenuWidth - spacing)

                                            var openerPos = mapToItem(Overlay.overlay, 0, 0)
                                            var submenuHeight = moveToMenu.implicitHeight > 0 ? moveToMenu.implicitHeight : (moveToMenu.height || 300)
                                            var targetY = Math.min(Math.max(0, openerPos.y - 10), Math.max(0, window.height - submenuHeight))
                                            moveToMenu.x = targetX
                                            moveToMenu.y = targetY
                                            moveToMenu.lastX = targetX
                                            moveToMenu.lastY = targetY
                                            moveToMenu.popup()
                                        }

                                        onTriggered: if (enabled) openSubmenu()
                                        onHoveredChanged: {
                                            if (hovered && enabled && contextMenu.visible) {
                                                openSubmenu()
                                            } else {
                                                moveToMenu.scheduleCloseIfUnhovered()
                                            }
                                        }
                                    }
                                    StyledMenuItem {
                                        font.pixelSize: 16
                                        visible: !isPluginItem
                                        text: qsTr("Add note")
                                        onTriggered: {
                                            noteDialog.openForClip(delegateRoot.clipId)
                                        }
                                    }
                                }

                                Timer {
                                    id: moveToCloseTimer
                                    interval: 50
                                    repeat: false
                                    onTriggered: {
                                        // Only close when neither the opener nor submenu is hovered; context menu must still be around
                                        if (!contextMenu.visible) {
                                            moveToMenu.close()
                                            return
                                        }
                                        if (moveToMenu.visible && !moveToMenu._hovering && !moveToOpener.hovered) {
                                            moveToMenu.close()
                                        }
                                    }
                                }

                                Menu {
                                    id: moveToMenu
                                    parent: window.contentItem
                                    Component.onCompleted: {
                                        if (Overlay.overlay) parent = Overlay.overlay
                                        close()
                                    }
                                    padding: 2
                                    topPadding: 10
                                    bottomPadding: 10
                                    implicitWidth: 200

                                    background: Rectangle {
                                        radius: 10
                                        color: grays[0]
                                        border.color: grays[3]
                                        border.width: 2
                                    }

                                    property var targets: []
                                    enabled: targets && targets.length > 0
                                    property bool isOpening: false
                                    property bool _hovering: false
                                    property real lastX: 0
                                    property real lastY: 0

                                    // Custom contentItem so HoverHandler sits on the real menu list
                                    contentItem: ListView {
                                        id: moveToList
                                        implicitHeight: contentHeight
                                        implicitWidth: contentWidth
                                        model: moveToMenu.contentModel
                                        interactive: false
                                        clip: true

                                        HoverHandler {
                                            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                                            grabPermissions: PointerHandler.TakeOverForbidden
                                            onHoveredChanged: {
                                                moveToMenu._hovering = hovered
                                                if (hovered) {
                                                    moveToCloseTimer.stop()
                                                } else {
                                                    moveToMenu.scheduleCloseIfUnhovered()
                                                }
                                            }
                                        }
                                    }

                                    function scheduleCloseIfUnhovered() {
                                        if (!visible) {
                                            moveToCloseTimer.stop()
                                            return
                                        }
                                        if (isOpening || _hovering || moveToOpener.hovered) {
                                            moveToCloseTimer.stop()
                                        } else {
                                            moveToCloseTimer.restart()
                                        }
                                    }

                                    onVisibleChanged: {
                                        if (visible) {
                                            if (lastX || lastY) {
                                                x = lastX
                                                y = lastY
                                            }
                                            moveToCloseTimer.stop()
                                        } else {
                                            isOpening = false
                                            _hovering = false
                                            moveToCloseTimer.stop()
                                        }
                                    }

                                    onOpened: {
                                        isOpening = false
                                        moveToCloseTimer.stop()
                                        scheduleCloseIfUnhovered()
                                    }

                                    MenuItem {
                                        text: qsTr("(No target)")
                                        enabled: false
                                        visible: !(moveToMenu.targets && moveToMenu.targets.length > 0)
                                        height: visible ? implicitHeight : 0
                                        padding: visible ? 6 : 0
                                        topPadding: visible ? 3 : 0
                                        bottomPadding: visible ? 3 : 0
                                    }

                                    Instantiator {
                                        id: moveInst
                                        model: moveToMenu.targets || []
                                        delegate: MenuItem {
                                            id: moveDelegate
                                            required property var modelData
                                            property var targetData: modelData
                                            property bool isCurrentForItem: targetData && targetData.isCurrent
                                            property var targetTags: (targetData && targetData.tags) ? targetData.tags : []

                                            text: targetData && targetData.name ? String(targetData.name) : ""
                                            font.pixelSize: 16
                                            enabled: !isCurrentForItem
                                            hoverEnabled: true
                                            leftPadding: 10
                                            rightPadding: 10
                                            topPadding: 4
                                            bottomPadding: 4
                                            background: Rectangle {
                                                anchors.fill: parent
                                                anchors.leftMargin: 6
                                                anchors.rightMargin: 6
                                                radius: 8
                                                color: moveDelegate.hovered ? grays[2] : "transparent"
                                                border.width: 0
                                            }
                                            contentItem: RowLayout {
                                                spacing: 6
                                                Label {
                                                    text: targetData && targetData.name ? String(targetData.name) : ""
                                                    color: grays[8]
                                                    font.pixelSize: 16
                                                    Layout.fillWidth: true
                                                    elide: Text.ElideRight
                                                }
                                                Repeater {
                                                    model: targetTags
                                                    delegate: Rectangle {
                                                        radius: 5
                                                        color: addAlphaToColor(grays[3], 0.9)
                                                        border.width: 0
                                                        height: tagLabel.implicitHeight + 6
                                                        width: tagLabel.implicitWidth + 10
                                                        Text {
                                                            id: tagLabel
                                                            anchors.centerIn: parent
                                                            text: modelData === "current-item-group" ? qsTr("*") : String(modelData)
                                                            color: grays[8]
                                                            font.pixelSize: 14
                                                            font.bold: true
                                                        }
                                                    }
                                                }
                                            }
                                            onTriggered: {
                                                if (targetData && targetData.id !== undefined)
                                                    backend.moveItemToGroup(delegateRoot.clipId, targetData.id)
                                            }
                                        }
                                        onObjectAdded: function(index, object) { moveToMenu.addItem(object) }
                                        onObjectRemoved: function(index, object) { moveToMenu.removeItem(object) }
                                    }
                                }

                                ToolButton {
                                    id: openBadge
                                    width: 30
                                    height: 30
                                    anchors.right: mainContent.right
                                    anchors.top: mainContent.top
                                    anchors.margins: 6
                                    anchors.topMargin: contentPanel.height - 36
                                    hoverEnabled: true
                                    z: 1
                                    visible: {
                                        if (delegateRoot.isImageContent) return true
                                        return rich.visible && (delegateRoot.richIsLong || delegateRoot.longByLength)
                                    }
                                    icon.source: iconsRoot + (delegateRoot.expanded ? "less.png" : "more.png")
                                    icon.color: "transparent"
                                    background: Rectangle {
                                        radius: 8
                                        color: openBadge.hovered ? (grays[8] || "#ddcccccc") : (addAlphaToColor(grays[6], 0.8) || "#cccccccc")
                                        border.width: 1
                                        border.color: openBadge.hovered ? highlightColors[2] : grays[3]
                                    }
                                    onClicked: {
                                        if (delegateRoot.isImageContent) {
                                            delegateRoot.expanded = !delegateRoot.expanded
                                            return
                                        }
                                        if (rich.visible && delegateRoot.richIsLong) {
                                            delegateRoot.expanded = !delegateRoot.expanded
                                            if (!delegateRoot.expanded) delegateRoot.longPressHoverPan = false
                                        }
                                    }
                                }

                                Row {
                                    anchors.top: mainContent.top
                                    anchors.right: mainContent.right
                                    anchors.margins: 6
                                    spacing: 6
                                    visible: delegateRoot.isHovered
                                    z: 1

                                    HoverHandler { id: actionHover }

                                    Repeater {
                                        model: [
                                            { key: "ocr", label: qsTr("OCR"), icon: "ocr.png", enabled: delegateRoot.clipContentType === "image", normal: addAlphaToColor(darkColors[0], 0.8), hover: lightColors[0] },
                                            { key: "translate", label: qsTr("Translate"), icon: "translate.png", enabled: delegateRoot.clipContentType !== "color", normal: addAlphaToColor(darkColors[1], 0.8), hover: lightColors[1] },
                                            { key: "improve", label: qsTr("Improve"), icon: "improve.png", enabled: !delegateRoot.isImageContent && delegateRoot.clipContentType !== "color", normal: addAlphaToColor(darkColors[2], 0.8), hover: lightColors[2] },
                                            { key: "summarize", label: qsTr("Summarize"), icon: "summarize.png", enabled: delegateRoot.clipContentType !== "color", normal: addAlphaToColor(darkColors[3], 0.8), hover: lightColors[3] },
                                            { key: "format", label: qsTr("Format"), icon: "format.png", enabled: delegateRoot.clipContentType !== "color", normal: addAlphaToColor(darkColors[4], 0.8), hover: lightColors[4] }
                                        ]
                                    delegate: ToolButton {
                                        visible: modelData.enabled && !delegateRoot.isPluginItem
                                        enabled: modelData.enabled && !delegateRoot.isPluginItem && !backend.operationRunning
                                            width: visible ? 30 : 0
                                            height: visible ? 30 : 0
                                            text: ""
                                            icon.source: iconsRoot + modelData.icon
                                            icon.color: "transparent"
                                            ToolTip.text: modelData.label
                                            background: Rectangle {
                                                radius: 10
                                                color: hovered ? (modelData.hover || modelData.normal || "#ddcccccc") : (modelData.normal || "#cccccccc")
                                                border.color: grays[3]
                                            }
                                            onClicked: {
                                                if (window.snapshotScrollForDelegate) window.snapshotScrollForDelegate(delegateRoot.clipId, delegateRoot.y)
                                                backend.runOperation(clipId, modelData.key)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    onCurrentIndexChanged: window.selectedClipId = clipModel.idAt(currentIndex)
                }
            }

            Rectangle {
                id: statusBar
                Layout.fillWidth: true
                Layout.preferredHeight: 28
                radius: 8
                color: grays[1]
                border.color: grays[3]
                visible: statusText.text !== ""
                opacity: 0.9

                Text {
                    id: statusText
                    anchors.fill: parent
                    anchors.margins: 8
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    color: grays[8]
                    text: ""
                    font.pixelSize: 14
                }
            }

            Timer {
                id: statusClearTimer
                interval: 2500
                repeat: false
                onTriggered: statusText.text = ""
            }
        }
    }

    // ===========================
    // Dialogs & helpers (outside rootFrame is OK)
    // ===========================
    Dialog {
        id: groupDialog
        parent: Overlay.overlay ? Overlay.overlay : window.contentItem
        modal: true
        property bool isRename: false
        property int targetId: -1
        header: null
        x: (window.width - width) / 2
        y: (window.height - height) / 2
        padding: 14
        background: Rectangle {
            radius: 12
            color: grays[1]
            border.color: grays[3]
            border.width: 2
        }
        contentItem: ColumnLayout {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 10
            Label { text: groupDialog.isRename ? qsTr("Rename") : qsTr("Create"); color: grays[8] }
            TextField {
                id: groupNameField
                Layout.fillWidth: true
                Layout.preferredHeight: 36
                font.pixelSize: 14
                color: grays[8]
                placeholderText: qsTr("Group name")
                background: Rectangle {
                    radius: 10
                    color: grays[1]
                    border.color: grays[3]
                    border.width: 2
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignHCenter
                spacing: 10
                Button {
                    text: "x"
                    font.pixelSize: 14
                    Layout.preferredWidth: 100
                    background: Rectangle {
                        radius: 10
                        color: grays[0]
                        border.color: grays[3]
                        border.width: 2
                    }
                    onClicked: groupDialog.reject()
                }
                Button {
                    text: "√"
                    font.pixelSize: 14
                    Layout.preferredWidth: 100
                    background: Rectangle {
                        radius: 10
                        color: grays[2]
                        border.color: grays[3]
                        border.width: 2
                    }
                    onClicked: groupDialog.accept()
                }
            }
        }
        onAccepted: {
            if (isRename) backend.renameGroup(targetId, groupNameField.text)
            else backend.createGroup(groupNameField.text)
            groupNameField.text = ""
        }
        onRejected: groupNameField.text = ""
        function openForCreate() {
            isRename = false
            targetId = -1
            groupNameField.text = ""
            open()
        }
        function openForRename(gid, name) {
            isRename = true
            targetId = gid
            groupNameField.text = name
            open()
        }
    }

    Dialog {
        id: noteDialog
        parent: Overlay.overlay ? Overlay.overlay : window.contentItem
        modal: true
        property int targetId: -1
        header: null
        x: (window.width - width) / 2
        y: (window.height - height) / 2
        padding: 14
        background: Rectangle {
            radius: 12
            color: grays[1]
            border.color: grays[3]
            border.width: 2
        }
        contentItem: ColumnLayout {
            width: 360
            spacing: 8
            anchors.margins: 12
            anchors.fill: parent

            Label {
                text: qsTr("Note text")
                color: grays[8]
                font.pixelSize: 16
            }
            TextField {
                id: noteField
                Layout.fillWidth: true
                Layout.preferredHeight: 36
                placeholderText: qsTr("Enter note...")
                selectByMouse: true
                font.pixelSize: 14
                color: grays[8]
                background: Rectangle {
                    radius: 10
                    color: grays[1]
                    border.color: grays[3]
                    border.width: 2
                }
                Keys.onReturnPressed: noteDialog.accept()
                Keys.onEnterPressed: noteDialog.accept()
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignHCenter
                spacing: 10
                Button {
                    text: "x"
                    font.pixelSize: 14
                    Layout.preferredWidth: 100
                    background: Rectangle {
                        radius: 10
                        color: grays[0]
                        border.color: grays[3]
                        border.width: 2
                    }
                    onClicked: noteDialog.reject()
                }
                Button {
                    text: "√"
                    font.pixelSize: 14
                    Layout.preferredWidth: 100
                    background: Rectangle {
                        radius: 10
                        color: grays[2]
                        border.color: grays[3]
                        border.width: 2
                    }
                    onClicked: noteDialog.accept()
                }
            }
        }
        onAccepted: backend.addNoteSubitem(targetId, noteField.text)
        onOpened: {
            noteField.text = ""
            noteField.forceActiveFocus()
        }
        onRejected: noteField.text = ""
        function openForClip(cid) {
            targetId = cid
            noteField.text = ""
            open()
        }
    }

    function confirmDeleteGroup(gid, name) {
        messageDialog.text = qsTr("Delete group \"%1\" ?").arg(name)
        messageDialog.gid = gid
        messageDialog.open()
    }

    Dialog {
        id: messageDialog
        property int gid: -1
        property string text: ""
        modal: true
        header: null
        parent: Overlay.overlay ? Overlay.overlay : window.contentItem
        x: (window.width - width) / 2
        y: (window.height - height) / 2
        padding: 14
        background: Rectangle {
            radius: 12
            color: grays[1]
            border.color: grays[3]
            border.width: 2
        }
        contentItem: ColumnLayout {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 12
            Label {
                text: messageDialog.text
                color: grays[8]
                font.pixelSize: 14
                wrapMode: Text.Wrap
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignHCenter
                spacing: 10
                Button {
                    text: "x"
                    font.pixelSize: 14
                    Layout.preferredWidth: 100
                    background: Rectangle {
                        radius: 10
                        color: grays[0]
                        border.color: grays[3]
                        border.width: 2
                    }
                    onClicked: messageDialog.reject()
                }
                Button {
                    text: "√"
                    font.pixelSize: 14
                    Layout.preferredWidth: 100
                    background: Rectangle {
                        radius: 10
                        color: grays[2]
                        border.color: grays[3]
                        border.width: 2
                    }
                    onClicked: messageDialog.accept()
                }
            }
        }
        onAccepted: backend.deleteGroup(gid)
    }

    Connections {
        target: backend
        function onStatusMessage(msg) {
            statusText.text = msg
            if (!msg || msg.length === 0) {
                statusClearTimer.stop()
                return
            }
            if (backend.operationRunning) {
                statusClearTimer.stop()
            } else {
                statusClearTimer.restart()
            }
        }
        function onOperationRunningChanged(running) {
            if (!running && statusText.text && statusText.text.length > 0) {
                statusClearTimer.restart()
            }
        }
        function onItemAdded(itemId, row) {
            if (row < 0) return
            window.pendingScrollRestore = false
            window.selectedClipId = itemId
            clipList.currentIndex = row
            Qt.callLater(function() {
                clipList.positionViewAtIndex(row, ListView.Beginning)
            })
        }
    }
}
