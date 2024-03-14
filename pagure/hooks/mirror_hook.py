# -*- coding: utf-8 -*-

"""
 (c) 2016-2018 - Copyright Red Hat Inc

 Authors:
   Pierre-Yves Chibon <pingou@pingoured.fr>

"""
from __future__ import absolute_import, unicode_literals

import sqlalchemy as sa
import wtforms

try:
    from flask_wtf import FlaskForm
except ImportError:
    from flask_wtf import Form as FlaskForm

from sqlalchemy.orm import backref, relation

import pagure.config
import pagure.lib.tasks_mirror
from pagure.hooks import BaseHook, BaseRunner, RequiredIf
from pagure.lib.model import BASE, Project
from pagure.utils import get_repo_path, ssh_urlpattern

_config = pagure.config.reload_config()


class MirrorTable(BASE):
    """Stores information about the mirroring hook deployed on a project.

    Table -- mirror_pagure
    """

    __tablename__ = "hook_mirror"

    id = sa.Column(sa.Integer, primary_key=True)
    project_id = sa.Column(
        sa.Integer,
        sa.ForeignKey("projects.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    active = sa.Column(sa.Boolean, nullable=False, default=False)

    public_key = sa.Column(sa.Text, nullable=True)
    target = sa.Column(sa.Text, nullable=True)
    last_log = sa.Column(sa.Text, nullable=True)

    project = relation(
        "Project",
        remote_side=[Project.id],
        backref=backref(
            "mirror_hook",
            cascade="delete, delete-orphan",
            single_parent=True,
            uselist=False,
        ),
    )


class MirrorRunner(BaseRunner):
    """Runner for the mirror hook."""

    @staticmethod
    def post_receive(
        session, username, project, repotype, repodir, changes, pull_request
    ):
        """Run the default post-receive hook.

        For args, see BaseRunner.runhook.
        """
        print("Running the default hook")
        if repotype != "main":
            if _config.get("HOOK_DEBUG", False):
                print("Default hook only runs on the main project repository")
                return

        pagure.lib.tasks_mirror.mirror_project.delay(
            username=project.user.user if project.is_fork else None,
            namespace=project.namespace,
            name=project.name,
        )


class CustomRegexp(wtforms.validators.Regexp):
    def __init__(self, *args, **kwargs):
        self.optional = kwargs.get("optional") or False
        if self.optional:
            kwargs.pop("optional")
        super(CustomRegexp, self).__init__(*args, **kwargs)

    def __call__(self, form, field):
        if self.optional:
            if field.data:
                return super(CustomRegexp, self).__call__(form, field)
        else:
            return super(CustomRegexp, self).__call__(form, field)


class MirrorForm(FlaskForm):
    """Form to configure the mirror hook."""

    active = wtforms.BooleanField("Active", [wtforms.validators.Optional()])

    target = wtforms.StringField(
        "Git repo to mirror to",
        [RequiredIf("active"), CustomRegexp(ssh_urlpattern, optional=True)],
    )

    public_key = wtforms.TextAreaField(
        "Public SSH key", [wtforms.validators.Optional()]
    )
    last_log = wtforms.TextAreaField(
        "Log of the last sync:", [wtforms.validators.Optional()]
    )


DESCRIPTION = """
Pagure specific hook to mirror a repo hosted on pagure to another location.

The first field below should contain the URL to be set in the git configuration
as the URL of the git repository to mirror to.
It's format is going to be something like:

    <user>@<host>:<path>

The public SSH key is being generated by pagure and will be available in this
page shortly after the activation of this hook. Just refresh the page until
it shows up.

Finally the log of the last sync at the bottom is meant.
"""


class MirrorHook(BaseHook):
    """Mirror hook."""

    name = "Mirroring"
    description = DESCRIPTION
    form = MirrorForm
    db_object = MirrorTable
    backref = "mirror_hook"
    form_fields = ["active", "target", "public_key", "last_log"]
    form_fields_readonly = ["public_key", "last_log"]
    runner = MirrorRunner

    @classmethod
    def install(cls, project, dbobj):
        """Method called to install the hook for a project.

        :arg project: a ``pagure.model.Project`` object to which the hook
            should be installed

        """
        pagure.lib.tasks_mirror.setup_mirroring.delay(
            username=project.user.user if project.is_fork else None,
            namespace=project.namespace,
            name=project.name,
        )

        repopaths = [get_repo_path(project)]
        cls.base_install(repopaths, dbobj, "mirror", "mirror.py")

    @classmethod
    def remove(cls, project):
        """Method called to remove the hook of a project.

        :arg project: a ``pagure.model.Project`` object to which the hook
            should be installed

        """
        pagure.lib.tasks_mirror.teardown_mirroring.delay(
            username=project.user.user if project.is_fork else None,
            namespace=project.namespace,
            name=project.name,
        )

        repopaths = [get_repo_path(project)]
        cls.base_remove(repopaths, "mirror")
