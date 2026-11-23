"""Operate the shared shell through its visible desktop or narrow controls."""


def shell_navigate(page, view):
    page.locator("#workspace").wait_for(state="visible")
    sidebar = page.locator("#app-sidebar")
    if not sidebar.is_visible():
        page.locator("#navigation-toggle").click()
    frame = page.frame_locator("#shell-navigation-frame")
    frame.locator("#page-select option").first.wait_for(state="attached")
    selector = frame.locator("#page-select")
    if selector.is_visible():
        selector.select_option(view)
    else:
        frame.locator(f'[data-view="{view}"]').click()
    page.locator(f"#view-{'search' if view == 'queue' else view}").wait_for(state="visible")


def shell_close_navigation(page):
    if page.locator("#app-sidebar").is_visible():
        page.locator("#navigation-toggle").click()


def shell_open_navigation(page):
    """The drawer on a phone closes after each choice; the preferences live inside it."""
    if not page.locator("#app-sidebar").is_visible():
        page.locator("#navigation-toggle").click()


def shell_close_drawer(page):
    """A phone's drawer covers the page; a tap on the dimmed page beside it closes it."""
    backdrop = page.locator("#navigation-backdrop")
    if backdrop.is_visible():
        box = backdrop.bounding_box()
        backdrop.click(position={"x": box["width"] - 8, "y": box["height"] / 2})


def media_option(page, selector):
    """Open the compact media menu before using one of its extra controls."""
    panel = page.frame_locator("#media-frame")
    control = panel.locator(selector)
    if not control.is_visible():
        panel.locator("#media-library-options > summary").click()
    return control
