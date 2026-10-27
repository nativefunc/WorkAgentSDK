import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'app.dart';
import 'glass/glass_shader.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  await GlassShader.preload();
  debugPrint(
    GlassShader.ready
        ? 'OpenMuse glass: liquid refraction ON (Impeller shader)'
        : 'OpenMuse glass: frosted fallback (no shader support)',
  );

  SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.dark,
      statusBarBrightness: Brightness.light,
      systemNavigationBarColor: Colors.transparent,
      systemNavigationBarIconBrightness: Brightness.dark,
      systemNavigationBarContrastEnforced: false,
    ),
  );

  runApp(const OpenMuseApp());
}
