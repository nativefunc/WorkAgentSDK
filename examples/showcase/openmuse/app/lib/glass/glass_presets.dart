import 'package:flutter/painting.dart';

import 'glass_settings.dart';

class GlassPresets {
  GlassPresets._();

  static const GlassSettings bar = GlassSettings(
    tint: Color(0x38FFFFFF),
    blur: 1.5,
    bevel: 20,
    ior: 1.3,
    dispersion: 0.1,
    lightIntensity: 1.3,
    saturation: 1.3,
    iridescence: 0.3,
  );

  static const GlassSettings control = GlassSettings(
    tint: Color(0x66FFFFFF),
    blur: 3,
    bevel: 12,
    ior: 1.2,
    dispersion: 0.05,
    lightIntensity: 1.4,
    saturation: 1.15,
    iridescence: 0.3,
  );

  static const GlassSettings darkControl = GlassSettings(
    tint: Color(0x1AFFFFFF),
    blur: 2,
    bevel: 14,
    ior: 1.3,
    dispersion: 0.06,
    lightIntensity: 1.3,
    saturation: 1.1,
    iridescence: 0.4,
  );

  static GlassSettings panel({double visibility = 1}) => GlassSettings(
    tint: const Color(0xD9FFFFFF),
    blur: 12,
    bevel: 10,
    ior: 1.1,
    dispersion: 0,
    lightIntensity: 1,
    saturation: 1.1,
    visibility: visibility,
  );

  static const GlassSettings selection = GlassSettings(
    tint: Color(0x16000000),
    blur: 0,
    bevel: 6,
    ior: 1.1,
    dispersion: 0.05,
    lightIntensity: 0.8,
    saturation: 1.1,
    iridescence: 0.15,
  );

  static GlassSettings lens({double visibility = 1}) => GlassSettings(
    tint: const Color(0x10FFFFFF),
    blur: 0,
    bevel: 9,
    ior: 1.4,
    dispersion: 0.15,
    lightIntensity: 1.6,
    saturation: 1.3,
    iridescence: 0.6,
    visibility: visibility,
    zoom: 1.1,
  );
}
