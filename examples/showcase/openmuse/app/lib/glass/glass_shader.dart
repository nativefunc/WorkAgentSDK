import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';

class GlassShader {
  GlassShader._();

  static const String _asset = 'shaders/glass_refraction.frag';

  static ui.FragmentProgram? _program;
  static bool _failed = false;

  static bool enabled = true;

  static bool get platformSupported =>
      !kIsWeb && ui.ImageFilter.isShaderFilterSupported;

  static bool get ready => enabled && _program != null && platformSupported;

  static Future<void> preload() async {
    if (_program != null || _failed || !platformSupported) return;
    try {
      _program = await ui.FragmentProgram.fromAsset(_asset);
    } catch (error) {
      _failed = true;
      debugPrint('GlassShader: falling back to frosted glass ($error)');
    }
  }

  static ui.FragmentShader? create() => _program?.fragmentShader();
}
