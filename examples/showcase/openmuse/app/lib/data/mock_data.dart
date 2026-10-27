class MockData {
  MockData._();

  static const List<Suggestion> suggestions = [
    Suggestion(
      'Summarize today’s tech news',
      'Open the browser, find today’s five biggest tech news stories and '
          'summarize each in one sentence, with links.',
    ),
    Suggestion(
      'Make me a to-do list file',
      'Create todo.md in the workspace with a short to-do list for today, '
          'then send me the file.',
    ),
    Suggestion(
      'Remind me to stretch at 3 pm',
      'Every weekday at 3 pm, remind me to get up and stretch.',
    ),
  ];
}

class Suggestion {
  const Suggestion(this.label, this.prompt);

  final String label;
  final String prompt;
}
