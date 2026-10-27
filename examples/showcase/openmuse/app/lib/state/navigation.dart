import 'package:flutter/widgets.dart';

class ShellNavigation extends ValueNotifier<int> {
  ShellNavigation() : super(0);

  static const int home = 0;
  static const int activity = 1;
  static const int profile = 2;

  void go(int tab) => value = tab;
}

class ShellScope extends InheritedNotifier<ShellNavigation> {
  const ShellScope({
    super.key,
    required ShellNavigation navigation,
    required super.child,
  }) : super(notifier: navigation);

  static ShellNavigation of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<ShellScope>();
    assert(scope != null, 'No ShellScope found in the widget tree.');
    return scope!.notifier!;
  }

  static ShellNavigation read(BuildContext context) {
    final scope = context.getInheritedWidgetOfExactType<ShellScope>();
    assert(scope != null, 'No ShellScope found in the widget tree.');
    return scope!.notifier!;
  }
}
