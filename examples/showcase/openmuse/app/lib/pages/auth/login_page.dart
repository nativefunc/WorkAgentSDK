import 'package:flutter/material.dart';

import '../../api/api_client.dart';
import '../../glass/pressable.dart';
import '../../state/auth_store.dart';
import '../../theme/app_theme.dart';

class LoginPage extends StatefulWidget {
  const LoginPage({super.key});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final TextEditingController _name = TextEditingController();
  final TextEditingController _email = TextEditingController();
  final TextEditingController _password = TextEditingController();
  final FocusNode _emailFocus = FocusNode();
  final FocusNode _passwordFocus = FocusNode();

  bool _register = false;
  bool _obscure = true;
  bool _busy = false;
  String? _error;

  static final RegExp _emailPattern = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');

  String? get _problem {
    if (!_emailPattern.hasMatch(_email.text.trim())) {
      return 'Enter a valid email address';
    }
    if (_register && _password.text.length < 8) {
      return 'Password must be at least 8 characters';
    }
    if (_password.text.isEmpty) return 'Enter your password';
    return null;
  }

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _password.dispose();
    _emailFocus.dispose();
    _passwordFocus.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_busy) return;
    final problem = _problem;
    if (problem != null) {
      setState(() => _error = problem);
      return;
    }
    FocusManager.instance.primaryFocus?.unfocus();
    setState(() {
      _busy = true;
      _error = null;
    });
    final auth = AuthScope.read(context);
    try {
      if (_register) {
        await auth.register(
          name: _name.text.trim(),
          email: _email.text.trim(),
          password: _password.text,
        );
      } else {
        await auth.signIn(email: _email.text.trim(), password: _password.text);
      }
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = error.message;
        });
      }
    }
  }

  void _toggleMode() {
    setState(() {
      _register = !_register;
      _error = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.canvas,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: AppLayout.formWidth),
              child: AutofillGroup(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const FittedBox(
                      fit: BoxFit.scaleDown,
                      child: Text(
                        AppInfo.name,
                        style: TextStyle(
                          fontSize: 34,
                          fontWeight: FontWeight.w700,
                          letterSpacing: -0.8,
                          color: AppColors.ink,
                        ),
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      _register
                          ? 'Create your account'
                          : 'Sign in with your email',
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        fontSize: 16,
                        color: AppColors.inkSecondary,
                      ),
                    ),
                    const SizedBox(height: 36),
                    AnimatedSize(
                      duration: const Duration(milliseconds: 220),
                      curve: Curves.easeOutCubic,
                      child: _register
                          ? Padding(
                              padding: const EdgeInsets.only(bottom: 10),
                              child: _Field(
                                child: TextField(
                                  controller: _name,
                                  enabled: !_busy,
                                  autofillHints: const [AutofillHints.name],
                                  textCapitalization: TextCapitalization.words,
                                  textInputAction: TextInputAction.next,
                                  onSubmitted: (_) =>
                                      _emailFocus.requestFocus(),
                                  style: const TextStyle(
                                    fontSize: 17,
                                    color: AppColors.ink,
                                  ),
                                  decoration: const InputDecoration.collapsed(
                                    hintText: 'Name',
                                    hintStyle: TextStyle(
                                      color: AppColors.inkTertiary,
                                    ),
                                  ),
                                ),
                              ),
                            )
                          : const SizedBox(width: double.infinity),
                    ),
                    _Field(
                      child: TextField(
                        controller: _email,
                        focusNode: _emailFocus,
                        enabled: !_busy,
                        keyboardType: TextInputType.emailAddress,
                        autofillHints: const [
                          AutofillHints.email,
                          AutofillHints.username,
                        ],
                        autocorrect: false,
                        textInputAction: TextInputAction.next,
                        onChanged: (_) => setState(() => _error = null),
                        onSubmitted: (_) => _passwordFocus.requestFocus(),
                        style: const TextStyle(
                          fontSize: 17,
                          color: AppColors.ink,
                        ),
                        decoration: const InputDecoration.collapsed(
                          hintText: 'Email',
                          hintStyle: TextStyle(color: AppColors.inkTertiary),
                        ),
                      ),
                    ),
                    const SizedBox(height: 10),
                    _Field(
                      trailing: Pressable(
                        onTap: () => setState(() => _obscure = !_obscure),
                        semanticLabel: _obscure
                            ? 'Show password'
                            : 'Hide password',
                        pressedScale: 0.88,
                        child: SizedBox.square(
                          dimension: 40,
                          child: Icon(
                            _obscure
                                ? Icons.visibility_outlined
                                : Icons.visibility_off_outlined,
                            size: 20,
                            color: AppColors.inkSecondary,
                          ),
                        ),
                      ),
                      child: TextField(
                        controller: _password,
                        focusNode: _passwordFocus,
                        enabled: !_busy,
                        obscureText: _obscure,
                        autocorrect: false,
                        enableSuggestions: false,
                        autofillHints: [
                          _register
                              ? AutofillHints.newPassword
                              : AutofillHints.password,
                        ],
                        textInputAction: TextInputAction.go,
                        onChanged: (_) => setState(() => _error = null),
                        onSubmitted: (_) => _submit(),
                        style: const TextStyle(
                          fontSize: 17,
                          color: AppColors.ink,
                        ),
                        decoration: InputDecoration.collapsed(
                          hintText: _register
                              ? 'Password (8+ characters)'
                              : 'Password',
                          hintStyle: const TextStyle(
                            color: AppColors.inkTertiary,
                          ),
                        ),
                      ),
                    ),
                    if (_error != null)
                      Padding(
                        padding: const EdgeInsets.fromLTRB(4, 10, 4, 0),
                        child: Text(
                          _error!,
                          style: const TextStyle(
                            fontSize: 13.5,
                            color: AppColors.danger,
                          ),
                        ),
                      ),
                    const SizedBox(height: 20),
                    _SubmitButton(
                      label: _register ? 'Create account' : 'Sign in',
                      busy: _busy,
                      onTap: _busy ? null : _submit,
                    ),
                    const SizedBox(height: 8),
                    Center(
                      child: GestureDetector(
                        onTap: _busy ? null : _toggleMode,
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Text.rich(
                            TextSpan(
                              text: _register
                                  ? 'Already have an account? '
                                  : 'New here? ',
                              children: [
                                TextSpan(
                                  text: _register
                                      ? 'Sign in'
                                      : 'Create an account',
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w600,
                                    color: AppColors.ink,
                                  ),
                                ),
                              ],
                            ),
                            style: const TextStyle(
                              fontSize: 14.5,
                              color: AppColors.inkSecondary,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Field extends StatelessWidget {
  const _Field({required this.child, this.trailing});

  final Widget child;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 56,
      padding: EdgeInsets.only(left: 18, right: trailing == null ? 18 : 6),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          Expanded(child: child),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}

class _SubmitButton extends StatelessWidget {
  const _SubmitButton({
    required this.label,
    required this.busy,
    required this.onTap,
  });

  final String label;
  final bool busy;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      semanticLabel: label,
      pressedScale: 0.97,
      child: Container(
        height: 54,
        alignment: Alignment.center,
        decoration: const ShapeDecoration(
          color: AppColors.ink,
          shape: StadiumBorder(),
        ),
        child: busy
            ? const SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(
                  strokeWidth: 2.2,
                  color: Colors.white,
                ),
              )
            : Text(
                label,
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                  color: Colors.white,
                ),
              ),
      ),
    );
  }
}
