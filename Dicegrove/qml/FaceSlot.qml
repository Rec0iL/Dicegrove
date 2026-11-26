import QtQuick
import QtQuick.Shapes

// One die face: shaped like the real face, takes an SVG by drop or click.
// Empty -> shows the number it will get; filled -> SVG thumbnail with rotate / clear.
Item {
    id: slot
    property int number: 1
    property string label: String(number)
    property string shape: "square"     // square | triangle | kite | pentagon | circle
    property string path: ""
    property int turn: 0                 // image rotation in degrees (multiples of 90)
    signal filesDropped(var urls)
    signal browse()
    signal rotate()
    signal clear()

    readonly property bool filled: path !== ""
    readonly property bool hovering: dropper.containsDrag
    implicitWidth: 110
    implicitHeight: 110

    // outline points in a 0..1 box
    readonly property var pts: ({
        "triangle": [[0.5, 0.05], [0.96, 0.88], [0.04, 0.88]],
        "kite":     [[0.5, 0.03], [0.9, 0.66], [0.5, 0.97], [0.1, 0.66]],
        "pentagon": [[0.5, 0.04], [0.96, 0.38], [0.78, 0.93], [0.22, 0.93], [0.04, 0.38]]
    })
    // where the artwork sits inside the shape: [centerX, centerY, size]
    readonly property var inner: ({
        "triangle": [0.5, 0.62, 0.44], "kite": [0.5, 0.56, 0.46], "pentagon": [0.5, 0.55, 0.58],
        "square": [0.5, 0.5, 0.72], "circle": [0.5, 0.5, 0.68]
    })[shape]

    readonly property color lineColor: hovering ? Theme.warm
                                     : filled ? Theme.accent2
                                     : Theme.dark ? Theme.edge(0.9) : Qt.rgba(0.50, 0.28, 0.75, 0.55)
    readonly property color fillColor: hovering ? Qt.rgba(1, 0.75, 0.3, 0.22)
                                     : filled ? Theme.glass(0.30) : Theme.glass(0.10)

    scale: hovering ? 1.06 : ma.containsMouse ? 1.025 : 1.0
    Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutBack } }

    // ---- face outline ------------------------------------------------------
    Rectangle {
        visible: slot.shape === "square" || slot.shape === "circle"
        anchors.fill: parent
        anchors.margins: 3
        radius: slot.shape === "circle" ? width / 2 : width * 0.16
        color: slot.fillColor
        border.width: slot.hovering ? 3 : 2
        border.color: slot.lineColor
    }
    Shape {
        visible: !(slot.shape === "square" || slot.shape === "circle")
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: slot.lineColor
            strokeWidth: slot.hovering ? 3 : 2
            fillColor: slot.fillColor
            joinStyle: ShapePath.RoundJoin
            strokeStyle: slot.filled ? ShapePath.SolidLine : ShapePath.DashLine
            dashPattern: [3, 2.5]
            PathPolyline {
                path: (slot.pts[slot.shape] || []).concat([(slot.pts[slot.shape] || [[0, 0]])[0]])
                      .map(p => Qt.point(p[0] * slot.width, p[1] * slot.height))
            }
        }
    }

    // ---- content -----------------------------------------------------------
    Item {
        id: content
        width: slot.width * slot.inner[2]
        height: width
        x: slot.width * slot.inner[0] - width / 2
        y: slot.height * slot.inner[1] - height / 2

        Image {
            anchors.fill: parent
            visible: slot.filled
            source: slot.filled ? Theme.fileUrl(slot.path) : ""
            sourceSize: Qt.size(256, 256)
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            smooth: true
            rotation: slot.turn
            Behavior on rotation { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        }
        Text {  // the number this face gets when it stays empty
            anchors.centerIn: parent
            visible: !slot.filled
            text: slot.label
            font.pixelSize: Math.max(12, Math.min(parent.height * (slot.label.length > 3 ? 0.32 : 0.62), 46))
            font.weight: Font.Bold
            font.family: Theme.font
            color: Theme.dark ? Qt.rgba(1, 1, 1, 0.38) : Qt.rgba(0.2, 0.1, 0.3, 0.32)
        }
    }

    // number badge (always visible, also when filled)
    Rectangle {
        visible: slot.filled
        width: Math.max(22, badge.implicitWidth + 10); height: 22; radius: 11
        x: slot.shape === "triangle" ? slot.width * 0.5 - width / 2 : 4
        y: slot.shape === "triangle" ? slot.height * 0.9 - 4
         : slot.shape === "kite" ? slot.height * 0.82 : 4
        color: Theme.accent
        Text { id: badge; anchors.centerIn: parent; text: slot.label; color: "white"
               font.pixelSize: 12; font.weight: Font.Bold; font.family: Theme.font }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: slot.browse()
    }

    // rotate / clear (on filled faces)
    Row {
        visible: slot.filled
        spacing: 4
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.topMargin: slot.shape === "triangle" || slot.shape === "kite" ? slot.height * 0.32 : 2
        anchors.rightMargin: slot.shape === "triangle" ? slot.width * 0.1 : 2
        component Mini_: Rectangle {
            id: mini
            property string glyph: ""
            signal hit()
            width: slot.width < 100 ? 18 : 24; height: width; radius: width / 2
            color: mm.containsMouse ? Theme.accent : Theme.glass(0.85)
            border.width: 1; border.color: Theme.fieldBorder
            Text { anchors.centerIn: parent; text: mini.glyph; font.pixelSize: mini.width * 0.54; font.weight: Font.Bold
                   color: mm.containsMouse ? "white" : Theme.text }
            MouseArea { id: mm; anchors.fill: parent; hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor; onClicked: mini.hit() }
        }
        Mini_ { glyph: "↻"; onHit: slot.rotate() }
        Mini_ { glyph: "✕"; onHit: slot.clear() }
    }

    DropArea {
        id: dropper
        anchors.fill: parent
        onDropped: (ev) => { if (ev.hasUrls) slot.filesDropped(ev.urls.map(u => u.toString())) }
    }
}
