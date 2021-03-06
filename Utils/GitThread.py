#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Created on 2019年1月5日
@author: Irony
@site: https://pyqt5.com https://github.com/892768447
@email: 892768447@qq.com
@file: Utils.GitThread
@description: Git operating thread
"""
from contextlib import closing
import os
from pathlib import Path
import shutil
import stat
from time import time
from zipfile import ZipFile

from PyQt5.QtCore import Qt, QCoreApplication, QThread, QObject
from PyQt5.QtGui import QImage
import pygit2
from pygit2.remote import RemoteCallbacks
import requests
from requests.auth import HTTPBasicAuth
from requests.exceptions import ConnectTimeout

from Utils import Constants, Version
from Utils.CommonUtil import Signals, AppLog


__Author__ = """By: Irony
QQ: 892768447
Email: 892768447@qq.com"""
__Copyright__ = "Copyright (c) 2019 Irony"
__Version__ = "Version 1.0"


class LoginThread(QObject):
    """Log in to Github, get the avatar
    """

    Url = 'https://api.github.com/user'

    def __init__(self, account, password, *args, **kwargs):
        super(LoginThread, self).__init__(*args, **kwargs)
        self.account = account
        self.password = password
    
    @classmethod
    def quit(cls):
        """Exit thread
        :param cls:
        """
        if hasattr(cls, '_thread'):
            cls._thread.quit()
            AppLog.info('login thread quit')

    @classmethod
    def start(cls, account, password, parent=None):
        """Start login thread
        :param cls:
        :param account:        account
        :param password:       password
        """
        cls._thread = QThread(parent)
        cls._worker = LoginThread(account, password)
        cls._worker.moveToThread(cls._thread)
        cls._thread.started.connect(cls._worker.run)
        cls._thread.finished.connect(cls._worker.deleteLater)
        cls._thread.start()
        AppLog.info('login thread started')

    def get_avatar(self, uid, avatar_url):
        try:
            req = requests.get(avatar_url)
            if req.status_code == 200:
                imgformat = req.headers.get(
                    'content-type', 'image/jpg').split('/')[1]
                Constants.ImageAvatar = os.path.join(
                    Constants.ImageDir, str(uid)).replace('\\', '/') + '.jpg'
                AppLog.debug('image type: {}'.format(imgformat))
                AppLog.debug(
                    'content length: {}'.format(len(req.content)))

                image = QImage()
                if image.loadFromData(req.content):
                    # 缩放图片
                    if not image.isNull():
                        image = image.scaled(130, 130, Qt.IgnoreAspectRatio,
                                             Qt.SmoothTransformation)
                        AppLog.debug('save to: {}'.format(
                            Constants.ImageAvatar))
                        image.save(Constants.ImageAvatar)
                    else:
                        AppLog.warn('avatar image is null')
                else:
                    AppLog.warn('can not load from image data')
        except Exception as e:
            AppLog.exception(e)

    def run(self):
        AppLog.info('start login github')
        try:
            req = requests.get(self.Url, auth=HTTPBasicAuth(
                self.account, self.password))
            retval = req.json()
            if retval.get('message', '') == 'Bad credentials':
                Signals.loginErrored.emit(QCoreApplication.translate(
                    'Repository', 'Incorrect account or password'))
                AppLog.warn('Incorrect account or password')
                LoginThread.quit()
                return
            if 'login' not in retval:
                Signals.loginErrored.emit(QCoreApplication.translate(
                    'Repository', 'Login failed, Unknown reason'))
                AppLog.warn('Login failed, Unknown reason')
                LoginThread.quit()
                return
            # User ID
            uid = retval.get('id', 0)
            AppLog.debug('user id: {}'.format(uid))
            # User's Nickname
            name = retval.get('name', 'Unknown')
            AppLog.debug('user name: {}'.format(name))
            # User avatar address
            avatar_url = retval.get('avatar_url', '')
            if avatar_url:
                # Get avatar
                self.get_avatar(uid, avatar_url)
            Signals.loginSuccessed.emit(str(uid), name)
        except ConnectTimeout as e:
            Signals.loginErrored.emit(QCoreApplication.translate(
                'Repository', 'Connect Timeout'))
            AppLog.exception(e)
        except ConnectionError as e:
            Signals.loginErrored.emit(QCoreApplication.translate(
                'Repository', 'Connection Error'))
            AppLog.exception(e)
        except Exception as e:
            Signals.loginErrored.emit(QCoreApplication.translate(
                'Repository', 'Unknown Error'))
            AppLog.exception(e)

        AppLog.info('login thread end')
        LoginThread.quit()


class ProgressCallback(RemoteCallbacks):
    """Scheps in the clone process
    """

    def transfer_progress(self, stats):
        Signals.progressUpdated.emit(
            stats.received_objects, stats.total_objects)
        AppLog.debug('total: {}, received: {}'.format(
            stats.total_objects, stats.received_objects))


class CloneThread(QObject):
    """Get project source code
    """

    Url = 'git://github.com/PyQt5/PyQt.git'
    
    @classmethod
    def quit(cls):
        """Exit thread
        :param cls:
        """
        if hasattr(cls, '_thread'):
            cls._thread.quit()
            AppLog.info('clone thread quit')

    @classmethod
    def start(cls, parent=None):
        """Start Clone thread
        :param cls:
        """
        cls._thread = QThread(parent)
        cls._worker = CloneThread()
        cls._worker.moveToThread(cls._thread)
        cls._thread.started.connect(cls._worker.run)
        cls._thread.finished.connect(cls._worker.deleteLater)
        cls._thread.start()
        AppLog.info('clone thread started')

    def pull(self, repo, remote_name='origin', branch='master'):
        """ pull changes for the specified remote (defaults to origin).

        Code from MichaelBoselowitz at:
        https://github.com/MichaelBoselowitz/pygit2-examples/blob/
            68e889e50a592d30ab4105a2e7b9f28fac7324c8/examples.py#L58
        licensed under the MIT license.
        """
        for remote in repo.remotes:
            if remote.name == remote_name:
                remote.fetch()
                remote_master_id = repo.lookup_reference(
                    'refs/remotes/origin/%s' % (branch)).target
                merge_result, _ = repo.merge_analysis(remote_master_id)
                # Up to date, do nothing
                if merge_result & pygit2.GIT_MERGE_ANALYSIS_UP_TO_DATE:
                    return
                # We can just fastforward
                elif merge_result & pygit2.GIT_MERGE_ANALYSIS_FASTFORWARD:
                    repo.checkout_tree(repo.get(remote_master_id))
                    try:
                        master_ref = repo.lookup_reference(
                            'refs/heads/%s' % (branch))
                        master_ref.set_target(remote_master_id)
                    except KeyError:
                        repo.create_branch(branch, repo.get(remote_master_id))
                    repo.head.set_target(remote_master_id)
                elif merge_result & pygit2.GIT_MERGE_ANALYSIS_NORMAL:
                    repo.merge(remote_master_id)

                    if repo.index.conflicts is not None:
                        for conflict in repo.index.conflicts:
                            print('Conflicts found in:', conflict[0].path)
                        raise AssertionError('Conflicts, ahhhhh!!')

                    user = repo.default_signature
                    tree = repo.index.write_tree()
                    repo.create_commit('HEAD', user, user,
                                       'Merge!', tree,
                                       [repo.head.target, remote_master_id])
                    # We need to do this or git CLI will think we are still
                    # merging.
                    repo.state_cleanup()
                else:
                    raise AssertionError('Unknown merge analysis result')

    def remove(self):
        """ Delete the directory """
        for path in Path(Constants.DirProjects).rglob('*'):
            path.chmod(stat.S_IWRITE)
        shutil.rmtree(Constants.DirProjects, ignore_errors=True)

    def clone(self):
        """ Cloning Project """
        pygit2.clone_repository(
            self.Url, Constants.DirProjects, callbacks=ProgressCallback())

    def run(self):
        try:
            path = pygit2.discover_repository(Constants.DirProjects)
            if not path:
                # Local project does not exist
                if os.path.exists(Constants.DirProjects):
                    # Delete if the folder exists
                    AppLog.info('remove dir: {}'.format(Constants.DirProjects))
                    self.remove()
                AppLog.info('clone into dir: {}'.format(Constants.DirProjects))
                self.clone()
            else:
                repo = pygit2.Repository(path)
                if repo.is_empty:  # If the project is empty
                    if os.path.exists(Constants.DirProjects):
                        # Delete if the folder exists
                        AppLog.info('remove dir: {}'.format(
                            Constants.DirProjects))
                        self.remove()
                    AppLog.info('clone into dir: {}'.format(
                        Constants.DirProjects))
                    self.clone()
                else:
                    # Reset and put
                    AppLog.info('reset dir: {}'.format(Constants.DirProjects))
                    repo.reset(repo.head.target, pygit2.GIT_RESET_HARD)
                    Signals.progressUpdated.emit(5, 100)
                    AppLog.info('pull into dir: {}'.format(
                        Constants.DirProjects))
                    self.pull(repo)
                    Signals.progressStoped.emit()
        except Exception as e:
            AppLog.exception(e)

        AppLog.info('clone thread end')
        Signals.progressStoped.emit()
        Signals.cloneFinished.emit('')
        CloneThread.quit()


class UpgradeThread(QObject):
    """Automatic update
    """

    Url = 'https://raw.githubusercontent.com/PyQt5/PyQtClient/master/.Update/Upgrade.json'
    ZipUrl = 'https://raw.githubusercontent.com/PyQt5/PyQtClient/master/.Update/Upgrade.{}.zip'

#     Url = 'https://raw.githubusercontent.com/IronyYou/test/master/Update/Upgrade.json'
#     ZipUrl = 'https://raw.githubusercontent.com/IronyYou/test/master/Update/Upgrade.{}.zip'
    
    @classmethod
    def quit(cls):
        """Exit thread
        :param cls:
        """
        if hasattr(cls, '_thread'):
            cls._thread.quit()
            AppLog.info('upgrade thread quit')

    @classmethod
    def start(cls, parent=None):
        """Start automatic update thread
        :param cls:
        """
        cls._thread = QThread(parent)
        cls._worker = UpgradeThread()
        cls._worker.moveToThread(cls._thread)
        cls._thread.started.connect(cls._worker.run)
        cls._thread.finished.connect(cls._worker.deleteLater)
        cls._thread.start()
        AppLog.info('update thread started')

    def unzip(self, file):
        # Decompression
        zipfile = ZipFile(file)
        path = os.path.abspath('.')
        members = zipfile.namelist()
        for zipinfo in members:
            _name = zipinfo.lower()
            if _name.endswith('.exe') or \
                    _name.endswith('.dll') or \
                    _name.endswith('.ttf') or \
                    _name.endswith('.so') or \
                    _name.endswith('.dylib'):
                tpath = os.path.abspath(os.path.join(path, zipinfo))
                # Need to rename the file currently occupied
                if os.path.isfile(tpath):
                    os.rename(tpath, tpath + str(time()) + '.old')
            zipfile.extract(zipinfo, path)
#             zipfile.extractall(os.path.abspath('.'))
        zipfile.close()

    def download(self, file, url):
        AppLog.debug('start download {}'.format(url))
        with closing(requests.get(url, stream=True)) as response:
            # Single request maximum
            chunk_size = 1024
            # Total size
            content_size = int(response.headers['content-length'])
            data_count = 0
            Signals.updateProgressChanged.emit(0, 0, content_size)
            AppLog.debug('content_size: {}'.format(content_size))
            with open(file, 'wb') as fp:
                for data in response.iter_content(chunk_size=chunk_size):
                    fp.write(data)
                    data_count = data_count + len(data)
                    if content_size > 0:
                        Signals.updateProgressChanged.emit(
                            data_count, 0, content_size)
            # Decompression
            self.unzip(file)
        AppLog.debug('download {} end'.format(file))

    def run(self):
        show = True
        try:
            req = requests.get(self.Url)
            AppLog.info(req.text)
            if req.status_code != 200:
                AppLog.info('update thread end')
                UpgradeThread.quit()
                return
            content = req.json()
            for version, text in content:
                if Version.version < version:
                    if show:
                        Signals.updateDialogShowed.emit()
                        QThread.msleep(1000)
                    show = False
                    Signals.updateTextChanged.emit(
                        str(Version.version), str(version), text)
                    self.download(Constants.UpgradeFile.format(
                        version), self.ZipUrl.format(version))
            Signals.updateFinished.emit(self.tr('update completed'))
        except Exception as e:
            Signals.updateFinished.emit(
                self.tr('update failed: {}').format(str(e)))
            AppLog.exception(e)
        AppLog.info('update thread end')
        UpgradeThread.quit()
