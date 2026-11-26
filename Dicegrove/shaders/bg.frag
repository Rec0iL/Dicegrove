#version 440
// Dicegrove background: wireframe dice (d20, d6, d8) tumbling slowly over dice-tray felt.
// Edges facing the viewer glow brighter (gold -> magenta); dragging / working spins
// them faster and makes them glow. Light theme: lavender parchment with ink lines.
// Uniform contract shared by every droplet - keep the block exactly like this.
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;        // accumulated animation time (already speed-scaled in QML)
    vec2 resolution;
    float energy;      // 0 = idle, 1 = excited (dragging / working)
    float quality;     // 1 = full, 0 = low power (skip expensive layers)
    float night;       // 0 = light theme, 1 = dark theme (animated in QML)
};

const float PHI = 1.6180339887;

float hash(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x),
               mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
}

float fbm(vec2 p) {
    float v = 0.0, a = 0.5;
    for (int i = 0; i < 4; i++) {
        v += a * noise(p);
        p = p * 2.03 + vec2(17.1, 3.7);
        a *= 0.5;
    }
    return v;
}

mat3 rotX(float a) { float c = cos(a), s = sin(a); return mat3(1, 0, 0, 0, c, s, 0, -s, c); }
mat3 rotY(float a) { float c = cos(a), s = sin(a); return mat3(c, 0, -s, 0, 1, 0, s, 0, c); }
mat3 rotZ(float a) { float c = cos(a), s = sin(a); return mat3(c, s, 0, -s, c, 0, 0, 0, 1); }

// vertex i of a polyhedron, circumradius 1. kind 0 = cube, 1 = octahedron, 2 = icosahedron
// (float math only: GLSL 100 es / 120 have no integer bit operations)
vec3 vert(int kind, int i) {
    float fi = float(i);
    float b0 = mod(fi, 2.0) * 2.0 - 1.0;               // bit 0 -> -1 / +1
    float b1 = mod(floor(fi / 2.0), 2.0) * 2.0 - 1.0;  // bit 1
    if (kind == 0) {
        float b2 = floor(fi / 4.0) * 2.0 - 1.0;         // bit 2
        return vec3(b0, b1, b2) / sqrt(3.0);
    }
    if (kind == 1) {
        float ax = floor(fi / 2.0);
        return ax < 0.5 ? vec3(b0, 0.0, 0.0) : ax < 1.5 ? vec3(0.0, b0, 0.0) : vec3(0.0, 0.0, b0);
    }
    float g = floor(fi / 4.0);
    vec3 v = g < 0.5 ? vec3(0.0, b0, b1 * PHI) : g < 1.5 ? vec3(b0, b1 * PHI, 0.0) : vec3(b1 * PHI, 0.0, b0);
    return v / sqrt(1.0 + PHI * PHI);
}

float segDist(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-6), 0.0, 1.0);
    return length(pa - ba * h);
}

// x = line intensity, y = vertex sparkle
vec2 polyhedron(vec2 p, int kind, vec2 c, float s, mat3 R, float px) {
    int n = kind == 0 ? 8 : kind == 1 ? 6 : 12;
    // squared edge length at circumradius 1
    float e2 = kind == 0 ? 4.0 / 3.0 : kind == 1 ? 2.0 : 4.0 / (1.0 + PHI * PHI);
    vec3 v[12];
    for (int i = 0; i < 12; i++) {
        if (i >= n) break;
        v[i] = R * vert(kind, i);
    }
    float lines = 0.0, dots = 0.0;
    float w = px * (1.1 + 0.9 * energy);
    for (int i = 0; i < 12; i++) {
        if (i >= n) break;
        vec2 a = c + v[i].xy * s;
        float front_v = 0.5 + 0.5 * v[i].z;
        dots += front_v * exp(-length(p - a) / (px * 2.2));
        for (int j = i + 1; j < 12; j++) {
            if (j >= n) break;
            vec3 d = v[i] - v[j];
            if (abs(dot(d, d) - e2) > 0.05) continue;
            float dist = segDist(p, a, c + v[j].xy * s);
            float front = 0.25 + 0.75 * (0.5 + 0.25 * (v[i].z + v[j].z));
            lines += front * (smoothstep(w * 1.6, 0.0, dist) * 0.85
                              + exp(-dist / (px * (5.0 + 7.0 * energy))) * (0.18 + 0.25 * energy));
        }
    }
    return vec2(lines, dots);
}

void main() {
    vec2 uv = qt_TexCoord0;
    float asp = resolution.x / resolution.y;
    vec2 p = (uv - 0.5) * vec2(asp, 1.0);
    float px = 1.0 / resolution.y;

    // ---- felt / parchment ------------------------------------------------------
    vec3 topL = vec3(0.95, 0.92, 0.98), botL = vec3(0.88, 0.83, 0.94);
    vec3 topD = vec3(0.09, 0.04, 0.14), botD = vec3(0.04, 0.02, 0.07);
    vec3 col = mix(mix(topL, botL, uv.y), mix(topD, botD, uv.y), night);
    if (quality > 0.5) {
        float felt = fbm(p * 7.0 + vec2(0.0, time * 0.01)) - 0.5;
        float fiber = noise(uv * resolution * 0.35) - 0.5;
        col += (felt * 0.05 + fiber * 0.018) * mix(vec3(0.55, 0.4, 0.7), vec3(0.6, 0.3, 0.8), night);
        // a soft magenta glow pooled around the big die
        col += mix(vec3(0.10, 0.02, 0.12), vec3(0.22, 0.04, 0.24), night)
               * exp(-length(p - vec2(0.30 * asp, -0.16)) * 2.4) * (0.6 + 0.6 * energy);
    }

    // ---- the dice ----------------------------------------------------------------
    float t = time * 0.22;
    vec2 d20 = polyhedron(p, 2, vec2(0.30 * asp, -0.16), 0.40,
                          rotY(t * 0.9) * rotX(t * 0.55 + 0.6) * rotZ(0.3), px);
    vec2 sum = d20;
    if (quality > 0.5) {
        sum += polyhedron(p, 0, vec2(-0.33 * asp, 0.24), 0.23,
                          rotX(-t * 0.7 + 1.1) * rotY(t * 0.45 + 0.4), px) * 0.9;
        sum += polyhedron(p, 1, vec2(-0.30 * asp, -0.30), 0.15,
                          rotY(-t * 1.1 + 2.0) * rotZ(t * 0.35), px) * 0.8;
    }

    vec3 gold = mix(vec3(0.55, 0.28, 0.70), vec3(1.00, 0.78, 0.36), night);
    vec3 magenta = mix(vec3(0.70, 0.16, 0.55), vec3(1.00, 0.31, 0.85), night);
    vec3 lineCol = mix(gold, magenta, clamp(uv.y * 1.2 - 0.1 + 0.25 * sin(time * 0.3), 0.0, 1.0));
    float lineA = mix(0.55, 0.85, night);
    col = mix(col, lineCol, clamp(sum.x * lineA, 0.0, 1.0));
    col += lineCol * sum.y * mix(0.25, 0.6, night) * (0.6 + 0.8 * energy);

    // ---- vignette + grain ------------------------------------------------------------
    col *= 1.0 - (0.18 + 0.20 * night) * dot(p * 0.9, p * 0.9);
    col += (hash(uv * resolution + fract(time)) - 0.5) * 0.018;
    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0) * qt_Opacity;
}
