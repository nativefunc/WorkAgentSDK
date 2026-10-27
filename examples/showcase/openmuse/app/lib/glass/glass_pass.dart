import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/rendering.dart';
import 'package:flutter/scheduler.dart';

import 'glass_settings.dart';
import 'glass_shader.dart';

class GlassShapeRect {
  const GlassShapeRect(this.rect, this.radius);

  final Rect rect;

  final double radius;
}

class GlassPass {
  GlassPass() : shader = GlassShader.create();

  static const int maxShapes = 8;

  final ui.FragmentShader? shader;
  final LayerHandle<BackdropFilterLayer> _blurLayer = LayerHandle();
  final LayerHandle<BackdropFilterLayer> _shaderLayer = LayerHandle();

  bool get available => shader != null;

  void configure({
    required List<GlassShapeRect> shapes,
    required Rect bounds,
    required GlassSettings settings,
    required double devicePixelRatio,
    double blend = 0,
    double edge = 0,
    double scale = 1,
  }) {
    final shader = this.shader;
    if (shader == null) return;
    final dpr = devicePixelRatio;
    final s = settings;
    final visibility = s.visibility.clamp(0.0, 1.0).toDouble();
    final angle = s.lightAngle * math.pi / 180;

    var i = 0;
    void f(double v) => shader.setFloat(i++, v);
    f(0);
    f(0);
    f(bounds.left * dpr);
    f(bounds.top * dpr);
    f(bounds.width * dpr);
    f(bounds.height * dpr);
    f(s.bevel * scale * dpr);
    f(s.ior);
    f(s.dispersion);
    f(s.tint.r);
    f(s.tint.g);
    f(s.tint.b);
    f(s.tint.a);
    f(math.cos(angle));
    f(-math.sin(angle));
    f(s.lightIntensity);
    f(s.saturation);
    f(visibility);
    f(blend * scale * dpr);
    f(edge);
    f(scale * dpr);

    final count = math.min(shapes.length, maxShapes);
    f(count.toDouble());
    for (var k = 0; k < maxShapes; k++) {
      if (k < count) {
        final r = shapes[k].rect;
        f(r.center.dx * dpr);
        f(r.center.dy * dpr);
        f(r.width / 2 * dpr);
        f(r.height / 2 * dpr);
        f(shapes[k].radius * dpr);
      } else {
        for (var z = 0; z < 5; z++) {
          f(0);
        }
      }
    }
    f(s.zoom);
    f(s.iridescence);
  }

  BackdropFilterLayer blurLayer(double sigma) {
    return (_blurLayer.layer ??= BackdropFilterLayer())
      ..filter = ui.ImageFilter.blur(
        sigmaX: sigma,
        sigmaY: sigma,
        tileMode: TileMode.mirror,
      );
  }

  BackdropFilterLayer shaderLayer() {
    return (_shaderLayer.layer ??= BackdropFilterLayer())
      ..filter = ui.ImageFilter.shader(shader!);
  }

  void dispose() {
    _blurLayer.layer = null;
    _shaderLayer.layer = null;
    shader?.dispose();
  }
}

Rect screenRectOf(RenderBox box) =>
    MatrixUtils.transformRect(box.getTransformTo(null), Offset.zero & box.size);

class TransformWatchLayer extends ContainerLayer {
  RenderBox? target;
  VoidCallback? onChanged;
  Rect? lastRect;

  @override
  bool get alwaysNeedsAddToScene => true;

  @override
  void addToScene(ui.SceneBuilder builder) {
    final box = target;
    if (box == null || !box.attached || !box.hasSize) return;
    final now = screenRectOf(box);
    if (now != lastRect) {
      lastRect = now;
      final callback = onChanged;
      if (callback != null) {
        SchedulerBinding.instance.addPostFrameCallback((_) => callback());
      }
    }
  }
}
