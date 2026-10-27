import 'package:flutter/widgets.dart';

final Set<String> _open = {};

const Duration _cooldown = Duration(milliseconds: 350);

Future<T?> singleFlight<T>(String key, Future<T?> Function() open) async {
  if (!_open.add(key)) return null;
  try {
    return await open();
  } finally {
    Future<void>.delayed(_cooldown, () => _open.remove(key));
  }
}

bool isTopRoute(BuildContext context) =>
    ModalRoute.of(context)?.isCurrent ?? false;

void popRoute<T extends Object?>(BuildContext context, [T? result]) {
  if (isTopRoute(context)) Navigator.of(context).pop<T>(result);
}
