OFFICE_STYLESHEET = """
QMainWindow, QWidget {
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 13px;
    color: #202124;
}
QMainWindow { background: #F3F5F8; }
#TitleRow {
    background: #E9F1FC;
    border-bottom: 1px solid #CAD5E3;
}
#AppTitle { font-size: 15px; font-weight: 600; color: #163A63; }
#SaveState { color: #526172; padding-left: 4px; }
QTabWidget#Ribbon::pane {
    border: 0;
    border-bottom: 1px solid #D5DCE5;
    background: #FFFFFF;
}
QTabWidget#Ribbon QTabBar::tab {
    background: #FFFFFF;
    padding: 9px 19px 8px 19px;
    border: 0;
    color: #3D4652;
}
QTabWidget#Ribbon QTabBar::tab:hover { background: #F1F6FC; }
QTabWidget#Ribbon QTabBar::tab:selected {
    color: #185ABD;
    font-weight: 600;
    border-bottom: 3px solid #185ABD;
}
#RibbonPage { background: #FFFFFF; }
#RibbonGroup {
    border-right: 1px solid #E2E6EC;
    padding: 3px 5px;
}
#RibbonGroupLabel { color: #697586; font-size: 11px; }
QPushButton, QToolButton {
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 7px 11px;
    background: transparent;
}
QPushButton:hover, QToolButton:hover {
    background: #EAF2FC;
    border-color: #BDD3EF;
}
QPushButton:pressed, QToolButton:pressed { background: #D6E7FA; }
QToolButton:checked {
    color: #0F4FA8;
    background: #DDEBFA;
    border-color: #8CB5E7;
    font-weight: 600;
}
QPushButton:disabled, QToolButton:disabled { color: #9AA1AA; }
QPushButton#PrimaryButton {
    color: #FFFFFF;
    background: #185ABD;
    padding: 10px 15px;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover { background: #0F4FA8; }
QGroupBox {
    font-weight: 600;
    background: #FFFFFF;
    border: 1px solid #DDE2E9;
    border-radius: 7px;
    margin-top: 14px;
    padding: 12px 8px 8px 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #344154;
}
QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #FFFFFF;
    border: 1px solid #C8D0DA;
    border-radius: 4px;
    padding: 5px;
    selection-background-color: #BDD7F5;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #3B7CC4;
}
QTableWidget {
    background: #FFFFFF;
    alternate-background-color: #F7F9FB;
    border: 1px solid #E0E5EB;
    border-radius: 5px;
    gridline-color: #E7EBF0;
    selection-background-color: #DCEAF9;
    selection-color: #202124;
}
QHeaderView::section {
    background: #F3F6F9;
    border: 0;
    border-bottom: 1px solid #D7DEE7;
    padding: 6px;
    font-weight: 600;
}
QTabWidget#DocumentTabs::pane, QTabWidget#SideTabs::pane { border: 0; }
QTabWidget#DocumentTabs QTabBar::tab, QTabWidget#SideTabs QTabBar::tab {
    padding: 8px 15px;
    background: #EDF0F4;
    border: 0;
}
QTabWidget#DocumentTabs QTabBar::tab:selected, QTabWidget#SideTabs QTabBar::tab:selected {
    color: #185ABD;
    background: #FFFFFF;
    font-weight: 600;
}
#DocumentArea { background: #E7EBF0; }
#DocumentPage, #PatternCanvas {
    background: #FFFFFF;
    border: 1px solid #CCD3DC;
}
#OutdatedBanner {
    background: #FFF4CE;
    color: #6B5700;
    padding: 8px 10px;
    border: 1px solid #E5D587;
    border-radius: 4px;
}
#PanelTitle {
    font-size: 14px;
    font-weight: 600;
    color: #2D3D52;
    padding: 9px 8px;
    background: #F8FAFC;
    border-bottom: 1px solid #D8DEE6;
}
#Backstage { background: #FFFFFF; }
#BackstageNav { background: #185ABD; color: #FFFFFF; }
#BackstageNav QPushButton {
    color: #FFFFFF;
    text-align: left;
    padding: 11px 18px;
    border-radius: 0;
}
#BackstageNav QPushButton:hover { background: #0F4FA8; border-color: transparent; }
QStatusBar {
    background: #FAFBFC;
    border-top: 1px solid #D8DEE6;
    color: #4E5B6B;
}
QScrollBar:vertical { width: 12px; background: #EEF1F4; }
QScrollBar:horizontal { height: 12px; background: #EEF1F4; }
QScrollBar::handle { background: #B8C0CB; border-radius: 5px; min-height: 24px; min-width: 24px; }
QScrollBar::handle:hover { background: #99A4B1; }
"""
