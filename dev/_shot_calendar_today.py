"""Visual probe: WednesdayCalendar with today highlighted (task 4)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QDate
import widgets

app = QApplication(sys.argv)
app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
cal = widgets.WednesdayCalendar()
cal.setSelectedDate(QDate.currentDate().addDays(5))   # selection elsewhere, to see both
cal.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
cal.resize(420, 360)
cal.show()
for _ in range(4):
    app.processEvents()
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots", "calendar_today.png")
cal.grab().save(out)
print(out, os.path.getsize(out))
