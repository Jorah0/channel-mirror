"""Channel Mirror - the master file: run this (or the built ChannelMirror.exe).

The app lives in cmlib/, one file per part (each file's first line says what it holds); this file loads them and
reads the command line. Every name of every part is also available here as channel_mirror.<name>, and setting one
(channel_mirror.X = ...) changes it in every part, as it did when the app was a single file.
"""
import sys
import types

# every part, in load order (the tabs build on the parts above them)
import cmlib.core
import cmlib.install
import cmlib.mirror
import cmlib.deck
import cmlib.vts
import cmlib.link
import cmlib.obs
import cmlib.peers
import cmlib.recorder
import cmlib.setup
import cmlib.music
import cmlib.docs
import cmlib.transcribe
import cmlib.ui
import cmlib.ui_link
import cmlib.dialogs
import cmlib.tab_import
import cmlib.tab_mover
import cmlib.tab_recorder
import cmlib.tab_vts
import cmlib.tab_link
import cmlib.tab_editor
import cmlib.tab_soundboard
import cmlib.tab_setup
import cmlib.tab_music
import cmlib.tab_obs
import cmlib.tab_transcribe
import cmlib.app

from cmlib.core import set_shared
from pathlib import Path
from cmlib.app import gui, uninstall_cli
from cmlib.install import install, shortcut_paths
from cmlib.link import link_args, link_to_peer
from cmlib.peers import link_handover

for _m in (
    cmlib.core, cmlib.install, cmlib.mirror, cmlib.deck, cmlib.vts, cmlib.link, cmlib.obs, cmlib.peers, cmlib.recorder,
    cmlib.setup, cmlib.music, cmlib.docs, cmlib.transcribe, cmlib.ui, cmlib.ui_link, cmlib.dialogs, cmlib.tab_import, cmlib.tab_mover,
    cmlib.tab_recorder, cmlib.tab_vts, cmlib.tab_link, cmlib.tab_editor, cmlib.tab_soundboard,
    cmlib.tab_setup, cmlib.tab_music, cmlib.tab_obs, cmlib.tab_transcribe, cmlib.app,
):
    globals().update({k: v for k, v in vars(_m).items() if not k.startswith("__")})


def selftest():
    from cmlib.selftest import selftest as run  # loaded only for --selftest
    try:
        run()
    except BaseException:  # a failed check exits at once (servers it started would otherwise keep the process alive)
        import os
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)


class _Master(types.ModuleType):
    def __setattr__(self, name, value):
        set_shared(name, value)  # every part that holds the name
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Master


if __name__ == "__main__":
    _link = link_args(sys.argv[1:])
    if _link:  # opened by a link: no other option on that command line counts (a link can't add --uninstall)
        if not link_handover(_link):
            gui()
    elif link_to_peer(sys.argv[1:]):  # Send to > Channel Mirror (linked computers): to the open app, else a new one
        if not link_handover(link_to_peer(sys.argv[1:])):
            gui()
    elif "--selftest" in sys.argv:
        selftest()
    elif "--uninstall" in sys.argv:
        uninstall_cli()
    elif "--install" in sys.argv and getattr(sys, "frozen", False):  # silent install for scripts: every shortcut, then done
        install(Path(sys.executable), links=shortcut_paths())
    else:
        gui()
