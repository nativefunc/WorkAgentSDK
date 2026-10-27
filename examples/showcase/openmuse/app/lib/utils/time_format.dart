class TimeFormat {
  TimeFormat._();

  static const List<String> _monthsShort = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ];

  static const List<String> _monthsLong = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
  ];

  static const List<String> _weekdays = [
    'Monday',
    'Tuesday',
    'Wednesday',
    'Thursday',
    'Friday',
    'Saturday',
    'Sunday',
  ];

  static String _two(int n) => n.toString().padLeft(2, '0');

  static int dayDifference(DateTime t, DateTime now) {
    final a = DateTime(t.year, t.month, t.day);
    final b = DateTime(now.year, now.month, now.day);
    return ((b.millisecondsSinceEpoch - a.millisecondsSinceEpoch) /
            Duration.millisecondsPerDay)
        .round();
  }

  static String clock(DateTime t) => '${_two(t.hour)}:${_two(t.minute)}';

  static String monthDay(DateTime t) => '${_monthsShort[t.month - 1]} ${t.day}';

  static String sessionStamp(DateTime t, DateTime now) {
    final days = dayDifference(t, now);
    if (days <= 0) return clock(t);
    if (days == 1) return 'Yesterday';
    if (days < 7) return _weekdays[t.weekday - 1];
    if (t.year == now.year) return monthDay(t);
    return '${t.year}/${t.month}/${t.day}';
  }

  static String sectionTitle(DateTime t, DateTime now) {
    final days = dayDifference(t, now);
    if (days <= 0) return 'Today';
    if (days == 1) return 'Yesterday';
    if (days < 7) return 'Previous 7 days';
    if (days < 30) return 'Previous 30 days';
    if (t.year == now.year) return _monthsLong[t.month - 1];
    return '${t.year}';
  }

  static String messageStamp(DateTime t, DateTime now) {
    final days = dayDifference(t, now);
    if (days <= 0) return clock(t);
    if (days == 1) return 'Yesterday ${clock(t)}';
    return '${monthDay(t)}, ${clock(t)}';
  }

  static String relative(DateTime t, DateTime now) {
    final diff = now.difference(t);
    if (diff.isNegative) return 'In ${_untilLabel(t, now)}';
    if (diff.inMinutes < 1) return 'Just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24 && dayDifference(t, now) == 0) {
      return '${diff.inHours}h ago';
    }
    return sessionStamp(t, now);
  }

  static String _untilLabel(DateTime t, DateTime now) {
    final diff = t.difference(now);
    if (diff.inMinutes < 60) return '${diff.inMinutes.clamp(1, 59)}m';
    if (diff.inHours < 24) return '${diff.inHours}h';
    return '${diff.inDays}d';
  }
}
