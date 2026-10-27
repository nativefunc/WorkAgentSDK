import 'package:flutter/material.dart';

import '../glass/app_tab_bar.dart';
import '../state/activity_store.dart';
import '../state/navigation.dart';
import '../theme/app_theme.dart';
import 'activity/activity_page.dart';
import 'home/home_page.dart';
import 'profile/profile_page.dart';

class RootShell extends StatelessWidget {
  const RootShell({super.key});

  List<AppTabItem> _tabs(bool attention) => [
    const AppTabItem(
      icon: Icons.chat_bubble_outline_rounded,
      activeIcon: Icons.chat_bubble_rounded,
      label: 'Home',
    ),
    AppTabItem(
      icon: Icons.bolt_outlined,
      activeIcon: Icons.bolt_rounded,
      label: 'Activity',
      badge: attention,
    ),
    const AppTabItem(
      icon: Icons.person_outline_rounded,
      activeIcon: Icons.person_rounded,
      label: 'Profile',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final navigation = ShellScope.of(context);
    final index = navigation.value;
    final attention = ActivityScope.of(context).attentionCount > 0;
    final keyboardOpen = MediaQuery.viewInsetsOf(context).bottom > 0;

    return Scaffold(
      backgroundColor: AppColors.canvas,
      resizeToAvoidBottomInset: false,
      body: Stack(
        children: [
          Positioned.fill(
            child: IndexedStack(
              index: index,
              children: [
                const HomePage(),
                ActivityPage(visible: index == ShellNavigation.activity),
                const ProfilePage(),
              ],
            ),
          ),
          Positioned(
            left: 0,
            right: 0,
            bottom: AppLayout.tabBarBottomGap(context),
            child: IgnorePointer(
              ignoring: keyboardOpen,
              child: AnimatedSlide(
                offset: keyboardOpen ? const Offset(0, 1.8) : Offset.zero,
                duration: const Duration(milliseconds: 260),
                curve: Curves.easeOutCubic,
                child: AnimatedOpacity(
                  opacity: keyboardOpen ? 0 : 1,
                  duration: const Duration(milliseconds: 180),
                  child: Center(
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(
                        maxWidth: AppLayout.tabBarMaxWidth,
                      ),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 28),
                        child: AppTabBar(
                          items: _tabs(attention),
                          currentIndex: index,
                          onChanged: (tab) {
                            if (tab == index) return;
                            FocusManager.instance.primaryFocus?.unfocus();
                            navigation.go(tab);
                          },
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
