import 'dart:ui' show Color, lerpDouble;

import 'package:flutter/foundation.dart';

@immutable
class GlassSettings {
  const GlassSettings({
    this.tint = const Color(0x40FFFFFF),
    this.blur = 4,
    this.bevel = 18,
    this.ior = 1.2,
    this.dispersion = 0.1,
    this.lightIntensity = 1.2,
    this.lightAngle = 135,
    this.saturation = 1.15,
    this.visibility = 1,
    this.zoom = 1,
    this.iridescence = 0,
  });

  final Color tint;

  final double blur;

  final double bevel;

  final double ior;

  final double dispersion;

  final double lightIntensity;

  final double lightAngle;

  final double saturation;

  final double visibility;

  final double zoom;

  final double iridescence;

  GlassSettings copyWith({
    Color? tint,
    double? blur,
    double? bevel,
    double? ior,
    double? dispersion,
    double? lightIntensity,
    double? lightAngle,
    double? saturation,
    double? visibility,
    double? zoom,
    double? iridescence,
  }) {
    return GlassSettings(
      tint: tint ?? this.tint,
      blur: blur ?? this.blur,
      bevel: bevel ?? this.bevel,
      ior: ior ?? this.ior,
      dispersion: dispersion ?? this.dispersion,
      lightIntensity: lightIntensity ?? this.lightIntensity,
      lightAngle: lightAngle ?? this.lightAngle,
      saturation: saturation ?? this.saturation,
      visibility: visibility ?? this.visibility,
      zoom: zoom ?? this.zoom,
      iridescence: iridescence ?? this.iridescence,
    );
  }

  static GlassSettings lerp(GlassSettings a, GlassSettings b, double t) {
    double l(double x, double y) => lerpDouble(x, y, t)!;
    return GlassSettings(
      tint: Color.lerp(a.tint, b.tint, t)!,
      blur: l(a.blur, b.blur),
      bevel: l(a.bevel, b.bevel),
      ior: l(a.ior, b.ior),
      dispersion: l(a.dispersion, b.dispersion),
      lightIntensity: l(a.lightIntensity, b.lightIntensity),
      lightAngle: l(a.lightAngle, b.lightAngle),
      saturation: l(a.saturation, b.saturation),
      visibility: l(a.visibility, b.visibility),
      zoom: l(a.zoom, b.zoom),
      iridescence: l(a.iridescence, b.iridescence),
    );
  }

  @override
  bool operator ==(Object other) =>
      other is GlassSettings &&
      other.tint == tint &&
      other.blur == blur &&
      other.bevel == bevel &&
      other.ior == ior &&
      other.dispersion == dispersion &&
      other.lightIntensity == lightIntensity &&
      other.lightAngle == lightAngle &&
      other.saturation == saturation &&
      other.visibility == visibility &&
      other.zoom == zoom &&
      other.iridescence == iridescence;

  @override
  int get hashCode => Object.hash(
    tint,
    blur,
    bevel,
    ior,
    dispersion,
    lightIntensity,
    lightAngle,
    saturation,
    visibility,
    zoom,
    iridescence,
  );
}
