#include <LayerShellQt/window.h>
#include <QMargins>
#include <QSize>
#include <QWindow>

// A small C ABI bridge so the PyQt window can use the installed LayerShellQt.
extern "C" int opentalk_layer(QWindow *window) {
    if (!window) {
        return 1;
    }
    auto layer = LayerShellQt::Window::get(window);
    layer->setLayer(LayerShellQt::Window::LayerOverlay);
    layer->setAnchors(LayerShellQt::Window::Anchors(LayerShellQt::Window::AnchorTop)
                      | LayerShellQt::Window::AnchorLeft);
    layer->setExclusiveZone(-1);
    layer->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityNone);
    layer->setMargins(QMargins(0, 0, 0, 0));
    layer->setDesiredSize(QSize(68, 68));
    layer->setWantsToBeOnActiveScreen(true);
    layer->setActivateOnShow(false);
    return 0;
}

extern "C" void opentalk_set_screen(QWindow *window, QScreen *screen) {
    if (window && screen) {
        LayerShellQt::Window::get(window)->setScreen(screen);
    }
}

extern "C" void opentalk_set_size(QWindow *window, int width, int height) {
    if (window && width > 0 && height > 0) {
        LayerShellQt::Window::get(window)->setDesiredSize(QSize(width, height));
    }
}

extern "C" void opentalk_set_position(QWindow *window, int x, int y) {
    if (window) {
        LayerShellQt::Window::get(window)->setMargins(QMargins(x, y, 0, 0));
        window->requestUpdate();
    }
}
