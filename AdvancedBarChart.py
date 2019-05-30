from typing import List, Optional, TypeVar

from PyQt5.QtGui import QMouseEvent, QPainter
from PyQt5.QtWidgets import QVBoxLayout, QWidget

from Axis import AutoGeneratedAxisDataSource, AxisBase
from BarChart import BarChartWidget
from Base import Alignment, DrawConfig, Orientation

T = TypeVar("T")


class CrossHairAxis(AxisBase):

    def __init__(self, orientation: "Orientation", underlying_axis: AxisBase):
        super().__init__(orientation)

        self.underlying_axis = underlying_axis
        self._drawer_value = 0

        self._links: List[CrossHairAxis] = []
        self._last_config: Optional["DrawConfig"] = None

    def set_value_by_ui_pos(self, pos: int):
        if self._last_config is None:
            return
        if self.orientation is Orientation.HORIZONTAL:
            value = self._last_config.drawing_cache.ui_x_to_drawer(pos)
        else:
            value = self._last_config.drawing_cache.ui_y_to_drawer(pos)
        self._set_drawer_value(value)

    def _set_drawer_value(self, value: float):
        if value != self._drawer_value:
            self._drawer_value = value
            self._sync_all_linked()

    def _sync_all_linked(self):
        for other in self._links:
            other._set_drawer_value(self._drawer_value)

    def sync_to(self, target: "CrossHairAxis"):
        assert target.orientation == self.orientation
        if self not in target._links:
            target._links.append(self)

    def prepare_draw_axis(self, config: "DrawConfig", painter: "QPainter") -> None:
        self._last_config = config
        self.underlying_axis.prepare_draw_axis(config, painter)

    def prepare_draw_grids(self, config: "DrawConfig", painter: "QPainter") -> None:
        self.underlying_axis.prepare_draw_grids(config, painter)

    def prepare_draw_labels(self, config: "DrawConfig", painter: "QPainter") -> None:
        self.underlying_axis.prepare_draw_labels(config, painter)

    def draw_grids(self, config: "DrawConfig", painter: QPainter):
        assert isinstance(
            self.underlying_axis.grid_drawer.data_source, AutoGeneratedAxisDataSource
        )
        ds = self.underlying_axis.grid_drawer.data_source
        ds.clear()

        value = self._drawer_value
        ds.append_by_index(value, Alignment.MID)

        self.underlying_axis.draw_grids(config, painter)

    def draw_labels(self, config: "DrawConfig", painter: QPainter):
        assert isinstance(
            self.underlying_axis.label_drawer.data_source, AutoGeneratedAxisDataSource
        )
        ds: "AutoGeneratedAxisDataSource" = self.underlying_axis.label_drawer.data_source
        ds.clear()

        value = self._drawer_value
        ds.append_by_index(value, Alignment.MID)

        self.underlying_axis.draw_labels(config, painter)


class CrossHairAxisX(CrossHairAxis):

    def __init__(self, underlying_axis: AxisBase):
        super().__init__(Orientation.HORIZONTAL, underlying_axis)


class CrossHairAxisY(CrossHairAxis):

    def __init__(self, underlying_axis: AxisBase):
        super().__init__(Orientation.VERTICAL, underlying_axis)


class ValuePanel(QWidget):
    pass


class SubChartWrapper:

    def __init__(self, chart: "BarChartWidget", cross_hair_x, cross_hair_y):
        self.cross_hair_y: CrossHairAxisY = cross_hair_y
        self.cross_hair_x: CrossHairAxisX = cross_hair_x
        self.chart = chart

    def create_cross_hair_x(self):
        assert self.cross_hair_x is None
        chart = self.chart
        axis_x_list = chart.all_axis_x
        if len(axis_x_list) == 0:
            return
        choose = axis_x_list[0]
        axis = CrossHairAxisX(choose)
        self.chart.add_axis(axis)
        self.cross_hair_x = axis
        return self

    def create_cross_hair_y(self):
        assert self.cross_hair_y is None
        chart = self.chart
        axis_y_list = chart.all_axis_y
        if len(axis_y_list) == 0:
            return
        choose = axis_y_list[0]
        axis = CrossHairAxisY(choose)
        self.chart.add_axis(axis)
        self.cross_hair_y = axis
        return self

    def create_cross_hair(self):
        self.create_cross_hair_x()
        self.create_cross_hair_y()
        return self

    def sync_x_to(self, target: "SubChartWrapper"):
        self.cross_hair_x.sync_to(target.cross_hair_x)

    def sync_y_to(self, target: "SubChartWrapper"):
        self.cross_hair_y.sync_to(target.cross_hair_y)


class AdvancedBarChart(QWidget):
    """
    AdvancedBarChart(ABC) is a  widget combining multiple BarChart.
    The data in different BarChart can have different Drawer and different DataSource,

    You can add multiple BarChart into one ABC.
    ABC also provide an Value Panel, and a CrossHair showing information about the value under cursor.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._sub_wrappers: List["SubChartWrapper"] = []

    def _init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(0)

        self.setLayout(main_layout)
        self.main_layout = main_layout

    def sub_chart_mouse_move(self, wrapper: "SubChartWrapper", event: "QMouseEvent"):
        pos = event.localPos()
        x = pos.x()
        y = pos.y()

        if wrapper.cross_hair_x:
            wrapper.cross_hair_x.set_value_by_ui_pos(x)
        if wrapper.cross_hair_y:
            wrapper.cross_hair_y.set_value_by_ui_pos(y)

        # todo: sync

    @property
    def chart_spacing(self):
        return self.main_layout.spacing()

    @chart_spacing.setter
    def chart_spacing(self, spacing: int):
        self.main_layout.setSpacing(spacing)

    def add_bar_chart(
        self,
        chart: "BarChartWidget",
        weight: int = 1,
        cross_hair_x: "CrossHairAxisX" = None,
        cross_hair_y: "CrossHairAxisY" = None,
    ):
        if chart not in [w.chart for w in self._sub_wrappers]:
            # fix padding
            left, right = 80, 10
            if self._sub_wrappers:
                last_chart = self._sub_wrappers[-1].chart
                l, t, r, b = last_chart.paddings
                last_chart.paddings = (l, t, r, 0)
            top, bottom = 0, 20
            chart.paddings = (left, top, right, bottom)

            # add axis as cross_hair
            if cross_hair_x:
                chart.add_axis(cross_hair_x)
            if cross_hair_y:
                chart.add_axis(cross_hair_y)
            wrapper = SubChartWrapper(chart, cross_hair_x, cross_hair_y)
            self.main_layout.addWidget(chart, weight)
            self._sub_wrappers.append(wrapper)

            def on_mouse_move(event):
                self.sub_chart_mouse_move(wrapper, event)

            chart.mouseMoveEvent = on_mouse_move
            chart.setMouseTracking(True)

            return wrapper
