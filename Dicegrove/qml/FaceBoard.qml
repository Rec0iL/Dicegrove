import QtQuick
import QtQuick.Layouts
import QtQuick.Dialogs

// One drop field per face, laid out in opposite pairs like a real die
// (1 opposite 6 on a d6 - opposite faces add up to sides + 1; coin: heads / tails).
Item {
    id: board
    property int sides: 6
    property var faces: []        // faces[k] = SVG path for face k+1 ("" = number)
    property var turns: []        // image rotation per face in degrees
    property string lastDir: ""
    signal message(string text)

    readonly property string tag: sides === 2 ? "coin" : "d" + sides
    readonly property bool paired: sides !== 4
    readonly property string shape: ({ 2: "circle", 4: "triangle", 6: "square", 8: "triangle",
                                       10: "kite", 12: "pentagon", 20: "triangle" })[sides] || "square"
    readonly property var columns: {
        const cols = []
        if (!paired) for (let k = 1; k <= sides; k++) cols.push([k])
        else for (let k = 1; k <= sides / 2; k++) cols.push([k, sides + 1 - k])
        return cols
    }
    readonly property int filledCount: {
        let n = 0
        for (let k = 0; k < sides; k++) if (faces[k]) n++
        return n
    }
    readonly property bool anyHover: {
        for (let i = 0; i < pairs.count; i++) {
            const it = pairs.itemAt(i)
            if (it && it.hovering) return true
        }
        return false
    }

    function labelOf(n) { return sides === 2 ? (n === 1 ? "Heads" : "Tails") : String(n) }
    function firstEmpty() {
        for (let k = 0; k < sides; k++) if (!faces[k]) return k + 1
        return 1
    }
    // put `paths` on face `face`, face+1, ... ; returns how many were placed
    function fillFrom(face, paths) {
        if (!paths || paths.length === 0) return 0
        if (face < 1) face = paths.length >= sides || filledCount === sides ? 1 : firstEmpty()
        const f = faces.slice(), t = turns.slice()
        let i = face - 1, used = 0
        for (const p of paths) {
            if (i >= sides) break
            f[i] = p; t[i] = 0; i++; used++
        }
        faces = f; turns = t
        if (paths.length > used)
            board.message((paths.length - used) + " SVG(s) did not fit on the " + tag + " - pick a bigger die")
        return used
    }
    function setFace(face, path) {
        const f = faces.slice(); f[face - 1] = path; faces = f
        const t = turns.slice(); t[face - 1] = 0; turns = t
    }
    function turnFace(face) {
        const t = turns.slice(); t[face - 1] = ((t[face - 1] || 0) + 90) % 360; turns = t
    }
    function clearAll() { faces = []; turns = [] }
    function make() {
        const f = [], t = []
        for (let k = 0; k < sides; k++) { f.push(faces[k] || ""); t.push(turns[k] || 0) }
        backend.makeDie(sides, f, t)
    }

    // sizes: the natural size (from the width) decides how tall the card wants to be;
    // the actual size also uses the height the card got, so fields grow on big windows
    readonly property int gap: sides >= 12 ? 10 : 18
    readonly property real connector: paired ? 20 : 0
    readonly property real widthSize: (width - gap * (columns.length - 1)) / columns.length
    readonly property real naturalSize: Math.max(64, Math.min(sides === 2 ? 150 : 128, widthSize))
    // pick how many pair-columns per row give the biggest fields (d20: 2 rows of 5 pairs)
    readonly property real availH: height - head.implicitHeight - 14 - 8
    function sizeFor(c) {
        const rows = Math.ceil(columns.length / c)
        const w = (width - gap * (c - 1)) / c
        const h = (availH - (rows - 1) * gap - rows * connector) / (rows * (paired ? 2 : 1))
        return Math.min(w, h, 190)
    }
    readonly property int bestCols: {
        // only balanced splits: columns = ceil(pairs / rows) -> 5 + 5, not 7 + 3
        let best = columns.length, bs = -1
        for (let r = 1; r <= columns.length; r++) {
            const c = Math.ceil(columns.length / r)
            const sz = sizeFor(c)
            if (sz > bs + 0.5) { bs = sz; best = c }
        }
        return best
    }
    readonly property real slotSize: Math.max(56, sizeFor(bestCols))
    implicitHeight: head.implicitHeight + 14 + (paired ? naturalSize * 2 + connector : naturalSize) + 8

    FileDialog {
        id: picker
        property int target: 1
        title: "SVG for face " + board.labelOf(target)
        fileMode: FileDialog.OpenFiles
        nameFilters: ["SVG images (*.svg)"]
        currentFolder: board.lastDir !== "" ? Theme.fileUrl(board.lastDir) : ""
        onAccepted: board.fillFrom(target, backend.expandFaces(selectedFiles.map(u => u.toString())))
    }

    // ---- top row: what is loaded + actions ----------------------------------
    RowLayout {
        id: head
        width: parent.width
        spacing: 12
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0
            Text {
                text: board.tag + "  ·  " + board.filledCount + " / " + board.sides
                      + (board.sides === 2 ? " sides" : " faces") + " with artwork"
                font.pixelSize: 17; font.weight: Font.Bold; font.family: Theme.font
                color: Theme.text
            }
            Text {
                Layout.fillWidth: true
                elide: Text.ElideRight
                text: board.sides === 2 ? "Heads on top, tails underneath. Empty sides get H / T."
                    : board.paired ? "Stacked faces are opposite - they add up to " + (board.sides + 1)
                                     + ". Empty faces get their number."
                    : "A d4 has no opposite faces. Empty faces get their number."
                font.pixelSize: 13; font.family: Theme.font; color: Theme.textSoft
            }
        }
        PillButton {
            visible: board.filledCount > 0
            label: "Clear all"; fontSize: 13
            onClicked: board.clearAll()
        }
        PillButton {
            label: board.sides === 2 ? "⚒  Make coin" : "⚒  Make " + board.tag
            primary: true
            onClicked: board.make()
        }
    }

    // ---- the faces --------------------------------------------------------------
    Flickable {
        id: flick
        anchors.top: head.bottom
        anchors.topMargin: 14
        anchors.bottom: parent.bottom
        width: parent.width
        contentHeight: flow.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Flow {
            id: flow
            readonly property real slotSize: board.slotSize
            width: Math.min(board.width, board.bestCols * (slotSize + board.gap) - board.gap)
            x: (board.width - width) / 2
            y: Math.max(0, (flick.height - height) / 2)
            spacing: board.gap

            Repeater {
                id: pairs
                model: board.columns
                delegate: Column {
                    id: pair
                    required property var modelData
                    readonly property bool twin: modelData.length > 1
                    readonly property bool hovering: top.hovering || (twin && bottom.hovering)
                    spacing: 2

                    FaceSlot {
                        id: top
                        number: pair.modelData[0]
                        width: flow.slotSize; height: flow.slotSize
                        shape: board.shape
                        label: board.labelOf(number)
                        path: board.faces[number - 1] || ""
                        turn: board.turns[number - 1] || 0
                        onFilesDropped: (urls) => board.fillFrom(number, backend.expandFaces(urls))
                        onBrowse: { picker.target = number; picker.open() }
                        onRotate: board.turnFace(number)
                        onClear: board.setFace(number, "")
                    }
                    Text {
                        visible: pair.twin
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "↕"
                        font.pixelSize: 14; font.weight: Font.Bold; font.family: Theme.font
                        color: Theme.textSoft
                    }
                    FaceSlot {
                        id: bottom
                        visible: pair.twin
                        number: pair.twin ? pair.modelData[1] : 1
                        width: flow.slotSize; height: flow.slotSize
                        shape: board.shape
                        label: board.labelOf(number)
                        path: pair.twin ? (board.faces[number - 1] || "") : ""
                        turn: board.turns[number - 1] || 0
                        onFilesDropped: (urls) => board.fillFrom(number, backend.expandFaces(urls))
                        onBrowse: { picker.target = number; picker.open() }
                        onRotate: board.turnFace(number)
                        onClear: board.setFace(number, "")
                    }
                }
            }
        }
    }
}
