import 'package:flutter/material.dart';

import '../../../data/mock_data.dart';
import '../../../glass/pressable.dart';
import '../../../theme/app_theme.dart';

class WelcomeView extends StatelessWidget {
  const WelcomeView({
    super.key,
    required this.topInset,
    required this.bottomInset,
    required this.onSuggestion,
  });

  final double topInset;
  final double bottomInset;
  final ValueChanged<String> onSuggestion;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final minHeight = (constraints.maxHeight - topInset - bottomInset)
            .clamp(0.0, double.infinity);
        return SingleChildScrollView(
          keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
          padding: EdgeInsets.fromLTRB(28, topInset, 28, bottomInset),
          child: ConstrainedBox(
            constraints: BoxConstraints(minHeight: minHeight),
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 420),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Text(
                      'What should I\nwork on today?',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: 28,
                        height: 1.18,
                        fontWeight: FontWeight.w600,
                        letterSpacing: -0.6,
                        color: AppColors.ink,
                      ),
                    ),
                    const SizedBox(height: 14),
                    const Text(
                      'I can browse the web, use the apps on your computer, '
                      'work with files and check in on a schedule.',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: 15,
                        height: 1.45,
                        color: AppColors.inkSecondary,
                      ),
                    ),
                    const SizedBox(height: 30),
                    for (final suggestion in MockData.suggestions)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: _SuggestionPill(
                          label: suggestion.label,
                          onTap: () => onSuggestion(suggestion.prompt),
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

class _SuggestionPill extends StatelessWidget {
  const _SuggestionPill({required this.label, required this.onTap});

  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      semanticLabel: label,
      pressedScale: 0.97,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
        decoration: const ShapeDecoration(
          color: Color(0xB3EDEDF2),
          shape: StadiumBorder(),
        ),
        child: Text(
          label,
          textAlign: TextAlign.center,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w600,
            color: AppColors.ink,
          ),
        ),
      ),
    );
  }
}
