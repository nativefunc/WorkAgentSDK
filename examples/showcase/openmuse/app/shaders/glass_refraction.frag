// OpenMuse liquid glass: backdrop refraction shader.
//
// Used as `ImageFilter.shader` in a BackdropFilter (Impeller only). The
// engine supplies the backdrop as sampler 0 and its size (device px) as the
// first vec2 uniform; everything else is set from Dart (glass_surface.dart).
//
// Renders 1–8 rounded shapes as one piece of glass. Nearby shapes are joined
// with a smooth union, so they flow into each other like drops of liquid.
//
// Optics: each shape's rim is a quarter-circle bevel of width uBevel. A view
// ray through the bevel is bent by Snell's law, pulling the backdrop near
// the edge inwards; the flat centre is undistorted. Then: per-channel
// offsets for dispersion, optional magnification and rainbow rim, a tint applied as screen (light) or multiply
// (dark), saturation, and an edge highlight that picks up the backdrop hue.
// With uEdge > 0 the shader also draws a hairline outline and a soft shadow
// around the merged outline (used by glass groups).
//
// Approach inspired by liquid_glass_renderer
// (https://github.com/whynotmake-it/flutter_liquid_glass).

#include <flutter/runtime_effect.glsl>

precision highp float;

#define MAX_SHAPES 8

uniform vec2 uSize;          // 0-1   backdrop size, device px (engine)
uniform vec4 uBounds;        // 2-5   area this pass covers, device px: x y w h
uniform float uBevel;        // 6     bevel width, device px
uniform float uIor;          // 7     index of refraction (1 = no bending)
uniform float uDispersion;   // 8     colour fringing, 0..1
uniform vec4 uTint;          // 9-12  tint rgb (straight) + strength
uniform vec2 uLight;         // 13-14 unit vector towards the light (y down)
uniform float uLightAmount;  // 15    highlight intensity
uniform float uSaturation;   // 16
uniform float uVisibility;   // 17    0..1
uniform float uBlend;        // 18    smooth-union radius, device px
uniform float uEdge;         // 19    outline + shadow strength (0 = off)
uniform float uPx;           // 20    device px per logical px
uniform float uCount;        // 21    number of shapes
uniform float uShapes[MAX_SHAPES * 5]; // 22-61 per shape: cx cy hw hh radius
uniform float uZoom;         // 62    magnification (single shape only)
uniform float uIris;         // 63    rainbow rim amount

uniform sampler2D uTexture;

out vec4 fragColor;

const vec3 kLuma = vec3(0.2126, 0.7152, 0.0722);

float roundedBox(vec2 p, vec2 halfSize, float r) {
  vec2 q = abs(p) - halfSize + vec2(r);
  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

// Polynomial smooth minimum.
float smoothUnion(float a, float b, float k) {
  if (k <= 0.0) return min(a, b);
  float h = max(k - abs(a - b), 0.0) / k;
  return min(a, b) - h * h * k * 0.25;
}

// Signed distance (device px) to one rounded box.
float shapeSd(vec2 p, vec2 c, vec2 h, float r) {
  return roundedBox(p - c, h, min(r, min(h.x, h.y)));
}

// Signed distance (device px) to the merged glass outline. Written out per
// shape with constant indices: dynamic indexing into a uniform array does
// not compile for every backend (SkSL rejects it).
float scene(vec2 p) {
  float d = shapeSd(p, vec2(uShapes[0], uShapes[1]), vec2(uShapes[2], uShapes[3]), uShapes[4]);
  if (uCount > 1.5) d = smoothUnion(d, shapeSd(p, vec2(uShapes[5], uShapes[6]), vec2(uShapes[7], uShapes[8]), uShapes[9]), uBlend);
  if (uCount > 2.5) d = smoothUnion(d, shapeSd(p, vec2(uShapes[10], uShapes[11]), vec2(uShapes[12], uShapes[13]), uShapes[14]), uBlend);
  if (uCount > 3.5) d = smoothUnion(d, shapeSd(p, vec2(uShapes[15], uShapes[16]), vec2(uShapes[17], uShapes[18]), uShapes[19]), uBlend);
  if (uCount > 4.5) d = smoothUnion(d, shapeSd(p, vec2(uShapes[20], uShapes[21]), vec2(uShapes[22], uShapes[23]), uShapes[24]), uBlend);
  if (uCount > 5.5) d = smoothUnion(d, shapeSd(p, vec2(uShapes[25], uShapes[26]), vec2(uShapes[27], uShapes[28]), uShapes[29]), uBlend);
  if (uCount > 6.5) d = smoothUnion(d, shapeSd(p, vec2(uShapes[30], uShapes[31]), vec2(uShapes[32], uShapes[33]), uShapes[34]), uBlend);
  if (uCount > 7.5) d = smoothUnion(d, shapeSd(p, vec2(uShapes[35], uShapes[36]), vec2(uShapes[37], uShapes[38]), uShapes[39]), uBlend);
  return d;
}

vec4 backdrop(vec2 devicePos, vec2 origin) {
  vec2 uv = (devicePos - origin) / uSize;
  // No GLES y-flip here: the engine already hands backdrop filters a
  // texture in screen orientation (flipping showed the backdrop upside down
  // on Android GLES).
  vec2 texel = 0.5 / uSize;
  return texture(uTexture, clamp(uv, texel, 1.0 - texel));
}

vec3 highlightColour(vec3 behind) {
  float luma = dot(behind, kLuma);
  float hi = max(max(behind.r, behind.g), behind.b);
  float lo = min(min(behind.r, behind.g), behind.b);
  float chroma = hi > 0.0 ? (hi - lo) / hi : 0.0;
  vec3 hue = behind / max(luma, 1e-3);
  hue = clamp(mix(vec3(dot(hue, kLuma)), hue, 1.25), 0.0, 1.0);
  float colourful = smoothstep(0.05, 0.6, luma) * smoothstep(0.05, 0.45, chroma);
  return mix(vec3(1.0), hue, colourful * 0.6);
}

void main() {
  vec2 frag = FlutterFragCoord().xy;

  // The backdrop is normally the whole screen; if an engine version crops it
  // to our bounds, switch to local coordinates.
  bool cropped = abs(uSize.x - uBounds.z) < 3.0 && abs(uSize.y - uBounds.w) < 3.0;
  vec2 origin = cropped ? uBounds.xy : vec2(0.0);
  vec2 device = frag + origin;

  vec4 original = backdrop(device, origin);
  float px = max(uPx, 1.0);
  float d = scene(device);

  // Outside the glass: only the group's soft shadow, if any.
  if (d > 1.0) {
    vec3 outside = original.rgb;
    if (uEdge > 0.0) {
      float ds = scene(device - vec2(0.0, 5.0 * px));
      float shade = exp(-max(ds, 0.0) / (7.0 * px)) * 0.10 * uEdge;
      float line = 1.0 - smoothstep(0.0, 0.6 * px, d);
      outside *= 1.0 - shade;
      outside = mix(outside, vec3(0.0), line * 0.10 * uEdge);
    }
    fragColor = vec4(outside, original.a);
    return;
  }

  vec2 grad = vec2(scene(device + vec2(1.0, 0.0)) - scene(device - vec2(1.0, 0.0)),
                   scene(device + vec2(0.0, 1.0)) - scene(device - vec2(0.0, 1.0)));
  vec2 n2 = length(grad) > 1e-4 ? normalize(grad) : vec2(0.0);

  // Bevel: `tilt` is the sine of the surface tilt, 1 at the outer wall and 0
  // on the flat top.
  float bevel = max(uBevel, 1.0);
  float depth = max(-d, 0.0);
  float tilt = clamp((bevel - depth) / bevel, 0.0, 1.0);
  float cosT = sqrt(max(0.0, 1.0 - tilt * tilt));
  float height = bevel * cosT;
  vec3 normal = normalize(vec3(n2 * tilt, cosT));

  // Snell's law for a ray looking straight down; it travels through the
  // glass height plus a small gap before hitting the backdrop.
  float ior = mix(1.0, max(uIor, 1.0), uVisibility);
  vec3 ray = refract(vec3(0.0, 0.0, -1.0), normal, 1.0 / ior);
  float travel = (height + bevel * 0.5) / max(abs(ray.z), 0.2);
  vec2 offset = ray.xy * travel;

  // Magnify around the shape's centre, like looking through a water drop.
  vec2 look = device;
  if (int(uCount + 0.5) == 1) {
    float zoom = mix(1.0, max(uZoom, 0.5), uVisibility);
    vec2 centre = vec2(uShapes[0], uShapes[1]);
    look = centre + (device - centre) / zoom;
  }

  float spread = uDispersion * 0.5 * uVisibility;
  vec3 c;
  c.r = backdrop(look + offset * (1.0 + spread), origin).r;
  c.g = backdrop(look + offset, origin).g;
  c.b = backdrop(look + offset * (1.0 - spread), origin).b;
  vec3 behind = c;

  float tintAmount = uTint.a * uVisibility;
  if (tintAmount > 0.0) {
    vec3 tinted = dot(uTint.rgb, kLuma) >= 0.5
        ? 1.0 - (1.0 - c) * (1.0 - uTint.rgb)
        : c * uTint.rgb * 2.0;
    c = mix(c, tinted, tintAmount);
  }

  float luma = dot(c, kLuma);
  c = mix(vec3(luma), c, mix(1.0, uSaturation, uVisibility));

  // Edge light, like iOS: a faint hairline all the way round plus two
  // bright arcs, one facing the light and a weaker one opposite. Kept close
  // to the outline; lighting the whole bevel turns round buttons into balls.
  float facing = dot(n2, uLight);
  float influence = max(facing, 0.0) + 0.8 * max(-facing, 0.0);
  float arcs = pow(influence, 2.5);
  float hair = exp(-depth / (0.9 * px));     // about one logical pixel
  float sheen = exp(-depth / (2.0 * px));    // soft glow inside the arcs
  float light = (0.3 * hair + arcs * (0.75 * hair + 0.35 * sheen)) *
                uLightAmount * uVisibility;

  // Iridescence: the rim and a thin film just inside it run through the
  // rainbow with the angle around the shape, like a soap bubble.
  vec3 rimColour = highlightColour(behind);
  float iris = uIris * uVisibility;
  if (iris > 0.0) {
    float turn = length(n2) > 0.0 ? atan(n2.y, n2.x) / 6.2831853 : 0.0;
    vec3 phase = vec3(turn * 2.0 + depth / (6.0 * px)) + vec3(0.0, 0.33, 0.67);
    vec3 rainbow = 0.5 + 0.5 * cos(6.2831853 * phase);
    rimColour = mix(rimColour, rainbow * 1.1, iris * 0.55);
    float film = exp(-depth / (3.0 * px)) * (1.0 - hair);
    c = mix(c, rainbow, film * iris * 0.18);
  }
  c = mix(c, rimColour, clamp(light, 0.0, 1.0));

  // Hairline just inside the outline (groups only).
  if (uEdge > 0.0) {
    float line = 1.0 - smoothstep(0.0, 0.6 * px, abs(d));
    c = mix(c, vec3(0.0), line * 0.10 * uEdge);
  }

  c = clamp(c, 0.0, 1.0);
  float inside = 1.0 - smoothstep(-1.0, 0.5, d);
  fragColor = vec4(mix(original.rgb, c, inside), original.a);
}
