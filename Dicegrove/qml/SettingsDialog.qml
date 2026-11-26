import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs

Popup {
    id: dlg
    property Item bgSource: null
    readonly property var s: backend.settings

    parent: Overlay.overlay
    anchors.centerIn: parent
    modal: true
    dim: true
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    width: Math.min(560, (parent ? parent.width : 560) - 40)
    height: Math.min(col.implicitHeight + 64, (parent ? parent.height : 700) - 40)

    Overlay.modal: Rectangle { color: Qt.rgba(0.10, 0.18, 0.40, 0.35) }
    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 200 }
            NumberAnimation { property: "scale"; from: 0.9; to: 1; duration: 320; easing.type: Easing.OutBack }
        }
    }
    exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: 150 } }

    FolderDialog {
        id: outPicker
        title: "Choose output folder"
        onAccepted: {
            backend.setSetting("customDir", backend.toLocalPath(selectedFolder.toString()))
            backend.setSetting("outputMode", "custom")
        }
    }

    background: Item {}
    contentItem: GlassCard {
        source: dlg.bgSource
        tintAlpha: 1.0
        blurred: false

        Flickable {
            anchors.fill: parent
            contentHeight: col.implicitHeight + 56
            clip: true
            boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: col
            width: parent.width - 56
            x: 28; y: 28
            spacing: 16

            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: "Settings"
                    font.pixelSize: 24; font.weight: Font.Bold; font.family: Theme.font; color: Theme.text
                    Layout.fillWidth: true
                }
                PillButton { label: "Done"; primary: true; onClicked: dlg.close() }
            }

            component Row_: RowLayout {
                id: rr
                property string title: ""
                property string hint: ""
                default property alias controls: holder.data
                Layout.fillWidth: true
                Layout.preferredWidth: 100000
                spacing: 12
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Text { text: rr.title; font.pixelSize: 15; font.weight: Font.DemiBold
                           font.family: Theme.font; color: Theme.text }
                    Text { visible: rr.hint !== ""; text: rr.hint; font.pixelSize: 12
                           font.family: Theme.font; color: Theme.textSoft; wrapMode: Text.WordWrap
                           Layout.fillWidth: true }
                }
                Row { id: holder; spacing: 8 }
            }

            Row_ {
                title: "Appearance"
                hint: dlg.s.theme === "auto" ? "Following your system theme" : ""
                Segmented {
                    model: ["Auto", "Light", "Dark"]
                    currentIndex: ["auto", "light", "dark"].indexOf(dlg.s.theme)
                    onActivated: (i) => backend.setSetting("theme", ["auto", "light", "dark"][i])
                }
            }

            // droopy:options begin   (one Row_ per exposed option - see references/options-mapping.md)
            component Section_: Text {
                Layout.topMargin: 6
                font.pixelSize: 13; font.weight: Font.Bold; font.family: Theme.font
                font.letterSpacing: 1.5; color: Theme.accent
            }
            component Num_: GlowSlider { width: 190 }

            Section_ { text: "DIE" }
            Row_ {
                title: "Size: " + (dlg.s.sizeMm > 0 ? dlg.s.sizeMm + " mm" : "typical")
                hint: "Face to face, coin: diameter. Typical = d4 20, d6/d8/d10 16, d12 18, d20 20, coin 30 mm."
                Num_ { from: 0; to: 60; stepSize: 1; value: dlg.s.sizeMm
                       onMoved: backend.setSetting("sizeMm", Math.round(value)) }
            }
            Row_ {
                title: "Coin thickness: " + Number(dlg.s.coinThickness).toFixed(1) + " mm"
                hint: "Only used for coins."
                Num_ { from: 2; to: 6; stepSize: 0.5; value: dlg.s.coinThickness
                       onMoved: backend.setSetting("coinThickness", Math.round(value * 10) / 10) }
            }
            Row_ {
                title: "Edges"
                hint: ["Sharp edges and corners.", "Evenly rounded edges and corners.",
                       "Corners cut by a sphere, like classic dice."][["none", "minkowski", "sphere"].indexOf(dlg.s.edges)]
                Segmented {
                    model: ["Sharp", "Rounded", "Classic"]
                    currentIndex: Math.max(0, ["none", "minkowski", "sphere"].indexOf(dlg.s.edges))
                    onActivated: (i) => backend.setSetting("edges", ["none", "minkowski", "sphere"][i])
                }
            }
            Row_ {
                visible: dlg.s.edges === "minkowski"
                title: "Rounding radius: " + Number(dlg.s.roundingMm).toFixed(1) + " mm"
                hint: "Coins use at most 0.6 mm."
                Num_ { from: 0.2; to: 3; stepSize: 0.1; value: dlg.s.roundingMm
                       onMoved: backend.setSetting("roundingMm", Math.round(value * 10) / 10) }
            }
            Row_ {
                title: "Inlay depth: " + Number(dlg.s.depthMm).toFixed(1) + " mm"
                hint: "How deep the colors go into the core. Use a multiple of your layer height."
                Num_ { from: 0.2; to: 1.2; stepSize: 0.1; value: dlg.s.depthMm
                       onMoved: backend.setSetting("depthMm", Math.round(value * 10) / 10) }
            }
            Row_ {
                title: "Layer height: " + Number(dlg.s.layerHeightMm).toFixed(2) + " mm"
                hint: "Only used to warn when the inlay depth is not a multiple of it."
                Num_ { from: 0.08; to: 0.32; stepSize: 0.04; value: dlg.s.layerHeightMm
                       onMoved: backend.setSetting("layerHeightMm", Math.round(value * 100) / 100) }
            }

            Section_ { text: "COLORS" }
            Row_ {
                title: "Max colors: " + dlg.s.maxColors
                hint: "Similar SVG colors are merged until this many are left (one filament each)."
                Num_ { from: 1; to: 8; stepSize: 1; value: dlg.s.maxColors
                       onMoved: backend.setSetting("maxColors", Math.round(value)) }
            }
            Row_ {
                title: "Core"
                hint: dlg.s.coreShares ? "The core is printed in one of the SVG colors; that color is not cut out."
                                       : "The core gets its own extra filament."
                Segmented {
                    model: ["Shares a color", "Own filament"]
                    currentIndex: dlg.s.coreShares ? 0 : 1
                    onActivated: (i) => backend.setSetting("coreShares", i === 0)
                }
            }
            Row_ {
                visible: dlg.s.coreShares
                title: "Core = color " + dlg.s.coreColorIndex
                hint: "Number from the color table in report.txt (1 = the color with the largest area)."
                Num_ { from: 1; to: 8; stepSize: 1; value: dlg.s.coreColorIndex
                       onMoved: backend.setSetting("coreColorIndex", Math.round(value)) }
            }
            Row_ {
                title: "Filament palette"
                hint: "Your real filaments, e.g. #ffffff, #d32f2f - SVG colors snap to them and color numbers follow this order. Empty = automatic."
                TextField {
                    width: 220
                    text: dlg.s.palette
                    placeholderText: "automatic"
                    color: Theme.text
                    placeholderTextColor: Theme.textSoft
                    font.family: Theme.font; font.pixelSize: 14
                    leftPadding: 14; rightPadding: 14
                    background: Rectangle { implicitHeight: 38; radius: 19; color: Theme.field
                                            border.width: 1; border.color: Theme.fieldBorder }
                    onEditingFinished: backend.setSetting("palette", text.trim())
                }
            }
            Row_ {
                title: "White = background"
                hint: "White areas in the SVGs are not cut - the core shows there."
                PillSwitch { checked: dlg.s.whiteBackground; onToggled: (v) => backend.setSetting("whiteBackground", v) }
            }

            Section_ { text: "ARTWORK" }
            Row_ {
                title: "Image size: " + dlg.s.imageScale + " %"
                hint: "Of the largest size that fits on the flat part of a face."
                Num_ { from: 50; to: 100; stepSize: 1; value: dlg.s.imageScale
                       onMoved: backend.setSetting("imageScale", Math.round(value)) }
            }
            Row_ {
                title: "Face margin: " + Number(dlg.s.faceMarginMm).toFixed(1) + " mm"
                hint: "Distance kept from the face edge and the rounding."
                Num_ { from: 0; to: 2; stepSize: 0.1; value: dlg.s.faceMarginMm
                       onMoved: backend.setSetting("faceMarginMm", Math.round(value * 10) / 10) }
            }
            Row_ {
                title: "Fit to"
                hint: dlg.s.fitTo === "viewbox" ? "The whole SVG page is scaled (keeps your framing)."
                                                : "The drawn shapes are scaled to fill the face."
                Segmented {
                    model: ["Drawing", "Page"]
                    currentIndex: dlg.s.fitTo === "viewbox" ? 1 : 0
                    onActivated: (i) => backend.setSetting("fitTo", i === 1 ? "viewbox" : "content")
                }
            }
            Row_ {
                title: "Same scale for all SVGs"
                hint: "For icon sets that share one page size. Numbers always share one size."
                PillSwitch { checked: dlg.s.uniformScale; onToggled: (v) => backend.setSetting("uniformScale", v) }
            }
            Row_ {
                title: "Thin details"
                hint: ["Strips thinner than the minimum join the neighboring color - shapes stay.",
                       "Strips thinner than the minimum become core color.",
                       "Nothing is changed - you get a warning and a size recommendation."][["merge", "remove", "keep"].indexOf(dlg.s.thinDetails)]
                Segmented {
                    model: ["Merge", "Remove", "Keep"]
                    currentIndex: Math.max(0, ["merge", "remove", "keep"].indexOf(dlg.s.thinDetails))
                    onActivated: (i) => backend.setSetting("thinDetails", ["merge", "remove", "keep"][i])
                }
            }
            Row_ {
                title: "Min feature width: " + Number(dlg.s.minFeatureMm).toFixed(2) + " mm"
                hint: "Usually your nozzle width. 0 = no check."
                Num_ { from: 0; to: 0.8; stepSize: 0.05; value: dlg.s.minFeatureMm
                       onMoved: backend.setSetting("minFeatureMm", Math.round(value * 100) / 100) }
            }

            Section_ { text: "FILES" }
            Row_ {
                title: "Part STLs"
                hint: "One STL per part (core, color 2, ...), all sharing one origin."
                PillSwitch { checked: dlg.s.writeStl; onToggled: (v) => backend.setSetting("writeStl", v) }
            }
            Row_ {
                title: "3MF projects"
                hint: "One for OrcaSlicer / Bambu Studio, one for PrusaSlicer - parts already have their filaments."
                PillSwitch { checked: dlg.s.write3mf; onToggled: (v) => backend.setSetting("write3mf", v) }
            }
            Row_ {
                title: "Preview image"
                hint: "preview.png with four views; shown on the job card."
                PillSwitch { checked: dlg.s.writePreview; onToggled: (v) => backend.setSetting("writePreview", v) }
            }
            Section_ { text: "GENERAL" }
            // droopy:options end

            Row_ {
                title: "Save to"
                hint: dlg.s.outputMode === "custom" && dlg.s.customDir !== "" ? dlg.s.customDir
                                                                               : "Right next to the original"
                Segmented {
                    model: ["Source folder", "Custom"]
                    currentIndex: dlg.s.outputMode === "custom" ? 1 : 0
                    onActivated: (i) => {
                        if (i === 1 && dlg.s.customDir === "") outPicker.open()
                        else backend.setSetting("outputMode", i === 1 ? "custom" : "source")
                    }
                }
                PillButton { visible: dlg.s.outputMode === "custom"; label: "Browse…"; onClicked: outPicker.open() }
            }
            Row_ {
                title: "If the output already exists"
                Segmented {
                    model: ["Rename", "Overwrite"]
                    currentIndex: dlg.s.overwrite === "overwrite" ? 1 : 0
                    onActivated: (i) => backend.setSetting("overwrite", i === 1 ? "overwrite" : "rename")
                }
            }
            Row_ {
                title: "Low-power background"
                hint: "Calmer animation, no glow - easier on the GPU."
                PillSwitch { checked: dlg.s.lowPower; onToggled: (v) => backend.setSetting("lowPower", v) }
            }
        }
        }
    }
}
