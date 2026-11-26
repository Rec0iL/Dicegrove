pragma Singleton
import QtQuick

// Light / dark palette. Everything is derived from `night` (0..1) which animates,
// so switching themes cross-fades the whole UI and the shader background.
QtObject {
    id: theme

    // "auto" follows the desktop colour scheme; set from Main.qml (settings.theme)
    property string mode: "auto"
    readonly property bool systemDark: Qt.styleHints.colorScheme === Qt.ColorScheme.Dark
    readonly property bool dark: mode === "dark" || (mode === "auto" && systemDark)

    property real night: dark ? 1 : 0
    Behavior on night { NumberAnimation { duration: 600; easing.type: Easing.InOutSine } }

    function mix(a, b, t) {
        const ca = Qt.color(a), cb = Qt.color(b)
        return Qt.rgba(ca.r + (cb.r - ca.r) * t, ca.g + (cb.g - ca.g) * t,
                       ca.b + (cb.b - ca.b) * t, ca.a + (cb.a - ca.a) * t)
    }
    function glass(alpha) {
        const base = mix(glassLight, glassDark, night)
        return Qt.rgba(base.r, base.g, base.b, Math.max(0, Math.min(1, alpha + night * 0.12)))
    }
    // local path -> file URL that also works on Windows (C:\x -> file:///C:/x)
    function fileUrl(p) {
        if (!p) return ""
        const s = String(p).replace(/\\/g, "/")
        return (s.startsWith("/") ? "file://" : "file:///") + encodeURI(s).replace(/#/g, "%23")
    }
    function edge(alpha) {
        return Qt.rgba(1, 1, 1, alpha * (1 - night * 0.72))
    }

    // droopy:palette begin   (edited per app in the look phase - light value, dark value)
    // Arcane: deep purple + magenta + gold, over plum felt (dark) / lavender parchment (light)
    readonly property color glassLight: "#fbf7ff"
    readonly property color glassDark: "#1a0f2b"
    readonly property color windowBg: mix("#efe7f6", "#0e0718", night)
    readonly property color text: mix("#2a1640", "#f3e9ff", night)
    readonly property color textSoft: mix("#66507e", "#b9a3d4", night)
    readonly property color dataText: mix("#8a5ab0", "#d7a6ff", night)   // background glyph layer
    readonly property color accent: mix("#8e2bd6", "#a64dff", night)     // primary (buttons, bars)
    readonly property color accent2: mix("#c4238f", "#ff4fd8", night)    // secondary (gradients)
    readonly property color mint: mix("#1f9f7a", "#4fe0b5", night)       // success
    readonly property color warm: mix("#c98a14", "#ffc857", night)       // gold: progress start, drop hover
    readonly property color danger: mix("#d6334f", "#ff6f86", night)
    readonly property color dangerBg: mix("#ffdbe3", "#4a1d2a", night)
    readonly property color pink: mix("#d43c9c", "#ff5fc8", night)       // slider gradient
    readonly property color lavender: mix("#8c55d8", "#b98bff", night)
    readonly property color field: mix(Qt.rgba(0.45, 0.20, 0.70, 0.12), Qt.rgba(1, 1, 1, 0.07), night)
    readonly property color fieldBorder: mix(Qt.rgba(0.45, 0.20, 0.70, 0.38), Qt.rgba(1, 1, 1, 0.22), night)
    readonly property color glyphGlow: mix("#c04fe0", "#ff4fd8", night)  // shadow of background glyphs
    readonly property color titleOutline: Qt.rgba(0.75, 0.25, 0.85, 0.5)
    readonly property string font: "Noto Sans"
    readonly property string mono: "Noto Sans Mono"
    // droopy:palette end

    readonly property color glassBorder: edge(0.70)
}
