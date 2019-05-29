from copy import copy
from threading import Lock
from typing import List, TYPE_CHECKING, TypeVar, Iterable

from PyQt5.QtCore import QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QPaintEvent, QPainter, QPen, QPicture, QTransform, QBrush, \
    QMouseEvent, QPalette
from PyQt5.QtWidgets import QWidget

from Axis import ValueAxis, ValueAxisX, ValueAxisY, AxisBase
from Base import ColorType, Orientation
from Drawer import DrawingCache, DrawConfig

if TYPE_CHECKING:
    from DataSource import DrawerBase

T = TypeVar("T")


def scale_from_mid(low, high, ratio):
    mid = (low + high) / 2
    scaled_range_2 = (high - low) / 2 * ratio
    return mid - scaled_range_2, mid + scaled_range_2


class ExtraDrawConfig(DrawConfig):

    def __init__(self):
        super().__init__()
        self.has_showing_data: bool = False


class BarChartWidget(QWidget):
    """
    用于管理二维平面图，目前只支持x坐标值为线性整数的图标。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.y_scale = 1.1
        self.plot_area_edge_color: "ColorType" = QColor(0, 0, 0)
        self.plot_area_edge_visible: bool = True
        # 注意，当bottom和right为0时，最下边和最右边的边框会因为越界而不显示
        # padding: (left, top, right, bottom)
        left, top, right, bottom = 20, 20, 20, 20
        self.paddings = [left, top, right, bottom]

        self._axis_list: List["AxisBase"] = []

        self._draw_config = ExtraDrawConfig()
        self._drawers: List["DrawerBase"] = []

        self._draw_config.begin = 0
        self._draw_config.end = 10

        self._repaint_lock = Lock()
        self._repaint_scheduled = False

        self.setMouseTracking(True)

    def add_drawer(self, drawer: "DrawerBase"):
        self._drawers.append(drawer)
        self.update()

    def set_x_range(self, begin: int, end: int):
        self._draw_config.begin, self._draw_config.end = begin, end
        self.update()

    @property
    def all_axis(self):
        return self._axis_list

    @property
    def all_axis_x(self):
        return [i for i in self._axis_list if i.orientation is Orientation.HORIZONTAL]

    @property
    def all_axis_y(self):
        return [i for i in self._axis_list if i.orientation is Orientation.VERTICAL]

    def add_axis(self, *axis_list: "AxisBase"):
        self._axis_list.extend(axis_list)

    def create_default_axis(self):
        """
        Create a ValueAxisX and a ValueAxisY then add to this chart.
        """
        assert len(self._axis_list) == 0
        self.add_axis(ValueAxisX(), ValueAxisY())

    def plot_area(self, config: "ExtraDrawConfig") -> "QRectF":
        """
        在UI坐标系中计算出绘制区域
        内部绘制函数无需调用该函数，查看config.output这个缓存的值即可
        """
        output: QRectF = QRectF(self.rect())

        left, top, right, bottom = self.paddings
        output2 = output.adjusted(left, top, -right, -bottom)
        return output2

    def drawer_to_ui(self, value: T, config: "ExtraDrawConfig" = None) -> T:
        """
        将value从drawer坐标系转到UI坐标系
        """
        if config is None:
            config = self._draw_config
        return config.drawing_cache.drawer_transform.map(value)

    #########################################################################
    # Re-implemented protected methods
    #########################################################################
    def paintEvent(self, event: "QPaintEvent"):
        # copy config: ensure config is not change while painting
        config: "ExtraDrawConfig" = copy(self._draw_config)

        config = self._prepare_painting(config)
        primary_painter = QPainter(self)
        primary_painter.setWorldMatrixEnabled(True)

        # 清除背景
        primary_painter.setBrush(self.palette().color(QPalette.Background))
        primary_painter.setPen(Qt.transparent)
        primary_painter.drawRect(primary_painter.window())

        # 绘制坐标轴
        self._paint_axis(config, primary_painter)

        # 绘制所有注册了的序列
        self._paint_drawers(config, primary_painter)

        # 绘制图表边框
        self._paint_box_edge(config, primary_painter)

        # 结束
        primary_painter.end()
        self._draw_config = config
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        event.ignore()

    #########################################################################
    # Private methods
    #########################################################################
    def _paint_drawers(self, config: "ExtraDrawConfig", painter: "QPainter"):
        if config.has_showing_data:
            for i, s in enumerate(self._drawers):
                if s.has_data():
                    self._switch_painter_to_drawer_coordinate(painter, config)
                    self._paint_drawer(s, config, painter)
            self._switch_painter_to_ui_coordinate(painter)

    def _paint_drawer(self, drawer: "DrawerBase", config: "ExtraDrawConfig", painter: "QPainter"):
        # painter = QPainter(layer)
        painter.setPen(QPen(Qt.transparent))
        drawer.draw(copy(config), painter)

    def _should_paint_axis(self, axis):
        return axis and axis.axis_visible and (axis.tick_visible or axis.grid_visible)

    def _paint_axis(self, config: "ExtraDrawConfig", painter: "QPainter"):
        axises = [i for i in self._axis_list if i and self._should_paint_axis(i)]
        for axis in axises:
            axis.prepare_draw_axis(copy(config), painter)

        # first: grid
        if config.has_showing_data:
            painter.setBrush(QColor(0, 0, 0, 0))
            for axis in axises:
                if axis.grid_visible:
                    axis.prepare_draw_grids(config, painter)
                    axis.draw_grids(copy(config), painter)

        # last: labels
        if config.has_showing_data:
            for axis in axises:
                if axis.tick_visible:
                    axis.prepare_draw_ticks(config, painter)
                    painter.setBrush(QColor(0, 0, 0, 0))
                    axis.draw_ticks(copy(config), painter)

    def _paint_box_edge(self, config: "ExtraDrawConfig", painter: "QPainter"):
        if self.plot_area_edge_visible:
            painter.setBrush(QBrush(Qt.transparent))
            painter.setPen(QPen(QColor(self.plot_area_edge_color)))
            painter.drawRect(config.drawing_cache.plot_area)

    def _prepare_painting(self, config: "ExtraDrawConfig"):
        """
        提前计算一些在绘图时需要的数据
        """
        # get preferred y range
        has_showing_data = config.end - config.begin
        config.has_showing_data = has_showing_data

        if has_showing_data and self._drawers:
            preferred_configs = [s.prepare_draw(copy(config)) for s in self._drawers if s.has_data()]
            if preferred_configs:
                y_low = min(preferred_configs, key=lambda c: c.y_low).y_low
                y_high = max(preferred_configs, key=lambda c: c.y_high).y_high
            else:
                y_low, y_high = 0, 1

            # scale y range
            config.y_low, config.y_high = scale_from_mid(y_low, y_high, self.y_scale)

        # 一些给其他类使用的中间变量，例如坐标转化矩阵
        self._prepare_drawing_cache(config)
        return config

    def _prepare_drawing_cache(self, config: "ExtraDrawConfig"):
        """
        生成一个矩阵用以将painter的坐标系从UI坐标系调整为drawer坐标系
        这样painter中的x和y轴就正好对应数据的x和y了

        """
        # 从UI坐标系到drawer坐标系的转化矩阵的构造顺序恰好相反，假设目前为drawer坐标系
        # 将drawer坐标转化为UI坐标
        drawer_area = QRectF(config.begin,
                             config.y_low,
                             max(config.end - config.begin, 1),
                             max(config.y_high - config.y_low, 1),
                             )
        plot_area = self.plot_area(config)
        # 应用这个坐标转化
        transform = self._coordinate_transform(drawer_area, plot_area)

        # 去除padding对上下翻转的影响
        transform *= QTransform.fromTranslate(0, -plot_area.top())

        # 在UI坐标系中上下翻转图像
        transform *= QTransform.fromTranslate(0, -plot_area.height())
        transform *= QTransform().rotate(180, Qt.XAxis)

        # 恢复padding
        transform *= QTransform.fromTranslate(0, plot_area.top())

        # 保存一些中间变量
        drawing_cache = DrawingCache()
        drawing_cache.drawer_transform = transform
        drawing_cache.ui_transform = transform.inverted()[0]
        drawing_cache.drawer_area = drawer_area
        # drawing_cache.drawer_area_width = drawer_area.width()
        # drawing_cache.drawer_area_height = drawer_area.height()
        drawing_cache.plot_area = plot_area
        # drawing_cache.plot_area_width = plot_area.width()
        # drawing_cache.plot_area_height = plot_area.height()

        drawing_cache.p2d_w = drawer_area.width() / plot_area.width()
        drawing_cache.p2d_h = drawer_area.height() / plot_area.height()

        config.drawing_cache = drawing_cache

    def _switch_painter_to_drawer_coordinate(self, painter: "QPainter", config: "ExtraDrawConfig"):
        """
        将painter的坐标系从UI坐标系调整为drawer坐标系
        这样painter中的x和y轴就正好对应数据的x和y了
        """
        painter.setWorldTransform(config.drawing_cache.drawer_transform)

    def _switch_painter_to_ui_coordinate(self, painter: "QPainter"):
        painter.setWorldMatrixEnabled(False)

    def _coordinate_transform(self, input: QRectF, output: QRectF):
        rx, ry = output.width() / input.width(), output.height() / input.height()
        t = QTransform.fromTranslate(-input.left(), -input.top())
        t *= QTransform.fromScale(rx, ry)
        t *= QTransform.fromTranslate(output.left(), output.top())
        return t
