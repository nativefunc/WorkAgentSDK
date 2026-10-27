import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/rendering.dart';
import 'package:flutter/widgets.dart';

import 'glass_pass.dart';
import 'glass_settings.dart';
import 'glass_shader.dart';

class GlassSurface extends StatelessWidget {
  const GlassSurface({
    super.key,
    required this.settings,
    this.child,
    this.radius = 24,
    this.circle = false,
    this.padding,
    this.width,
    this.height,
    this.shadow = true,
    this.outline = true,
    this.strength = 1,
  });

  final GlassSettings settings;
  final Widget? child;

  final double radius;

  final bool circle;

  final EdgeInsetsGeometry? padding;
  final double? width;
  final double? height;
  final bool shadow;
  final bool outline;

  final double strength;

  @override
  Widget build(BuildContext context) {
    final ShapeBorder shape = circle
        ? const StadiumBorder()
        : RoundedRectangleBorder(
            borderRadius: BorderRadius.all(Radius.circular(radius)),
          );

    Widget content = child ?? const SizedBox.shrink();
    if (padding != null) content = Padding(padding: padding!, child: content);

    Widget glass = GlassShader.ready
        ? ClipPath(
            clipper: ShapeBorderClipper(
              shape: shape,
              textDirection: Directionality.maybeOf(context),
            ),
            child: _Refraction(
              settings: settings,
              radius: circle ? double.infinity : radius,
              devicePixelRatio: MediaQuery.devicePixelRatioOf(context),
              child: content,
            ),
          )
        : _FrostedGlass(shape: shape, settings: settings, child: content);

    if (width != null || height != null) {
      glass = SizedBox(width: width, height: height, child: glass);
    }

    final edge = strength.clamp(0.0, 1.0).toDouble();
    if (edge == 0 || (!shadow && !outline)) return glass;

    final textDirection = Directionality.maybeOf(context);
    return CustomPaint(
      painter: shadow ? _ShadowPainter(shape, edge, textDirection) : null,
      foregroundPainter: outline
          ? _OutlinePainter(shape, edge, textDirection)
          : null,
      child: glass,
    );
  }
}

class _Refraction extends SingleChildRenderObjectWidget {
  const _Refraction({
    required this.settings,
    required this.radius,
    required this.devicePixelRatio,
    super.child,
  });

  final GlassSettings settings;
  final double radius;
  final double devicePixelRatio;

  @override
  RenderObject createRenderObject(BuildContext context) => _RenderRefraction(
    settings: settings,
    radius: radius,
    devicePixelRatio: devicePixelRatio,
  );

  @override
  void updateRenderObject(
    BuildContext context,
    _RenderRefraction renderObject,
  ) {
    renderObject
      ..settings = settings
      ..radius = radius
      ..devicePixelRatio = devicePixelRatio;
  }
}

class _RenderRefraction extends RenderProxyBox {
  _RenderRefraction({
    required GlassSettings settings,
    required double radius,
    required double devicePixelRatio,
  }) : _settings = settings,
       _radius = radius,
       _devicePixelRatio = devicePixelRatio;

  final GlassPass _pass = GlassPass();
  final LayerHandle<TransformWatchLayer> _watch = LayerHandle();

  GlassSettings _settings;
  set settings(GlassSettings value) {
    if (value == _settings) return;
    _settings = value;
    markNeedsPaint();
  }

  double _radius;
  set radius(double value) {
    if (value == _radius) return;
    _radius = value;
    markNeedsPaint();
  }

  double _devicePixelRatio;
  set devicePixelRatio(double value) {
    if (value == _devicePixelRatio) return;
    _devicePixelRatio = value;
    markNeedsPaint();
  }

  @override
  bool get alwaysNeedsCompositing => true;

  @override
  void paint(PaintingContext context, Offset offset) {
    if (!_pass.available || size.isEmpty) {
      super.paint(context, offset);
      return;
    }

    final screen = screenRectOf(this);
    final scale = screen.width / size.width;
    _pass.configure(
      shapes: [
        GlassShapeRect(
          screen,
          math.min(_radius, size.shortestSide / 2) * scale,
        ),
      ],
      bounds: screen,
      settings: _settings,
      devicePixelRatio: _devicePixelRatio,
      scale: scale,
    );

    final watch = _watch.layer ??= TransformWatchLayer();
    watch
      ..target = this
      ..lastRect = screen
      ..onChanged = () {
        if (attached) markNeedsPaint();
      };
    context.pushLayer(watch, (context, offset) {}, offset);

    void refract(PaintingContext context, Offset offset) {
      context.pushLayer(_pass.shaderLayer(), super.paint, offset);
    }

    final blur =
        _settings.blur * _settings.visibility.clamp(0.0, 1.0).toDouble();
    if (blur > 0.01) {
      context.pushLayer(_pass.blurLayer(blur), refract, offset);
    } else {
      refract(context, offset);
    }
  }

  @override
  void dispose() {
    _watch.layer = null;
    _pass.dispose();
    super.dispose();
  }
}

class _FrostedGlass extends StatelessWidget {
  const _FrostedGlass({
    required this.shape,
    required this.settings,
    required this.child,
  });

  final ShapeBorder shape;
  final GlassSettings settings;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final textDirection = Directionality.maybeOf(context);
    final visibility = settings.visibility.clamp(0.0, 1.0).toDouble();
    final blur = settings.blur * visibility;

    Widget body = CustomPaint(
      painter: _FrostPainter(shape, settings, visibility, textDirection),
      foregroundPainter: _RimPainter(
        shape,
        settings,
        visibility,
        textDirection,
      ),
      child: child,
    );
    if (blur > 0.01) {
      body = BackdropFilter(
        filter: ui.ImageFilter.blur(sigmaX: blur * 2, sigmaY: blur * 2),
        child: body,
      );
    }
    return ClipPath(
      clipper: ShapeBorderClipper(shape: shape, textDirection: textDirection),
      child: body,
    );
  }
}

class _FrostPainter extends CustomPainter {
  _FrostPainter(this.shape, this.settings, this.visibility, this.textDirection);

  final ShapeBorder shape;
  final GlassSettings settings;
  final double visibility;
  final TextDirection? textDirection;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty || visibility <= 0) return;
    final rect = Offset.zero & size;
    final path = shape.getOuterPath(rect, textDirection: textDirection);
    final tint = settings.tint;
    final a = tint.a * visibility;

    canvas.drawPath(
      path,
      Paint()
        ..shader = LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [
            tint.withValues(alpha: a),
            tint.withValues(alpha: a * 0.75),
          ],
        ).createShader(rect),
    );

    final sheen = (0.12 * settings.lightIntensity * visibility).clamp(
      0.0,
      0.45,
    );
    canvas.drawPath(
      path,
      Paint()
        ..shader = LinearGradient(
          begin: const Alignment(-0.6, -1),
          end: const Alignment(0.6, 1),
          colors: [
            const Color(0xFFFFFFFF).withValues(alpha: sheen),
            const Color(0x00FFFFFF),
            const Color(0x00FFFFFF),
            const Color(0xFFFFFFFF).withValues(alpha: sheen * 0.3),
          ],
          stops: const [0, 0.45, 0.8, 1],
        ).createShader(rect),
    );
  }

  @override
  bool shouldRepaint(_FrostPainter old) =>
      old.shape != shape ||
      old.settings != settings ||
      old.visibility != visibility;
}

class _RimPainter extends CustomPainter {
  _RimPainter(this.shape, this.settings, this.visibility, this.textDirection);

  final ShapeBorder shape;
  final GlassSettings settings;
  final double visibility;
  final TextDirection? textDirection;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty || visibility <= 0) return;
    final rect = Offset.zero & size;
    final path = shape.getOuterPath(
      rect.deflate(1.1),
      textDirection: textDirection,
    );
    final rim = (0.45 * settings.lightIntensity * visibility).clamp(0.0, 1.0);

    canvas.drawPath(
      path,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.2
        ..shader = LinearGradient(
          begin: const Alignment(-0.6, -1),
          end: const Alignment(0.6, 1),
          colors: [
            const Color(0xFFFFFFFF).withValues(alpha: rim),
            const Color(0xFFFFFFFF).withValues(alpha: rim * 0.2),
            const Color(0xFFFFFFFF).withValues(alpha: rim * 0.2),
            const Color(0xFFFFFFFF).withValues(alpha: rim * 0.6),
          ],
          stops: const [0, 0.4, 0.6, 1],
        ).createShader(rect),
    );
  }

  @override
  bool shouldRepaint(_RimPainter old) =>
      old.shape != shape ||
      old.settings != settings ||
      old.visibility != visibility;
}

class _OutlinePainter extends CustomPainter {
  _OutlinePainter(this.shape, this.strength, this.textDirection);

  final ShapeBorder shape;
  final double strength;
  final TextDirection? textDirection;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty) return;
    final path = shape.getOuterPath(
      (Offset.zero & size).deflate(0.25),
      textDirection: textDirection,
    );
    canvas.drawPath(
      path,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 0.5
        ..color = const Color(0xFF000000).withValues(alpha: 0.1 * strength),
    );
  }

  @override
  bool shouldRepaint(_OutlinePainter old) =>
      old.shape != shape || old.strength != strength;
}

class _ShadowPainter extends CustomPainter {
  _ShadowPainter(this.shape, this.strength, this.textDirection);

  final ShapeBorder shape;
  final double strength;
  final TextDirection? textDirection;

  static const double _blur = 16;
  static const Offset _offset = Offset(0, 6);

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty) return;
    final rect = Offset.zero & size;
    final shapePath = shape.getOuterPath(rect, textDirection: textDirection);

    final outside = Path()
      ..fillType = PathFillType.evenOdd
      ..addRect(rect.inflate(_blur * 3 + _offset.distance))
      ..addPath(shapePath, Offset.zero);

    canvas.save();
    canvas.clipPath(outside);
    canvas.drawPath(
      shapePath.shift(_offset),
      Paint()
        ..color = const Color(0xFF101028).withValues(alpha: 0.12 * strength)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, _blur / 2),
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(_ShadowPainter old) =>
      old.shape != shape || old.strength != strength;
}
