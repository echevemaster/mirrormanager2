# -*- coding: utf-8 -*-
#
# Copyright © 2014, 2015  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions
# of the GNU General Public License v.2, or (at your option) any later
# version.  This program is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY expressed or implied, including the
# implied warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR
# PURPOSE.  See the GNU General Public License for more details.  You
# should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# Any Red Hat trademarks that are incorporated in the source
# code or documentation are not subject to the GNU General Public
# License and may only be used or replicated with the express permission
# of Red Hat, Inc.
#

'''
MirrorManager2 main flask controller.
'''


import logging
import logging.handlers
import os
import sys

import flask

from functools import wraps
from flask.ext.admin import Admin
from sqlalchemy.exc import SQLAlchemyError

from mirrormanager2 import __version__

APP = flask.Flask(__name__)

APP.config.from_object('mirrormanager2.default_config')
if 'MM2_CONFIG' in os.environ:  # pragma: no cover
    APP.config.from_envvar('MM2_CONFIG')

ADMIN = Admin(APP)


# Points the template and static folders to the desired theme
APP.template_folder = os.path.join(
    APP.template_folder, APP.config['THEME_FOLDER'])
APP.static_folder = os.path.join(
    APP.static_folder, APP.config['THEME_FOLDER'])


# Set up the logger
# Send emails for big exception
MAIL_HANDLER = logging.handlers.SMTPHandler(
    APP.config.get('SMTP_SERVER', '127.0.0.1'),
    'nobody@fedoraproject.org',
    APP.config.get('MAIL_ADMIN', 'admin@fedoraproject.org'),
    'MirrorManager2 error')
MAIL_HANDLER.setFormatter(logging.Formatter('''
    Message type:       %(levelname)s
    Location:           %(pathname)s:%(lineno)d
    Module:             %(module)s
    Function:           %(funcName)s
    Time:               %(asctime)s

    Message:

    %(message)s
'''))
MAIL_HANDLER.setLevel(logging.ERROR)
if not APP.debug:
    APP.logger.addHandler(MAIL_HANDLER)

# Log to stderr as well
STDERR_LOG = logging.StreamHandler(sys.stderr)
STDERR_LOG.setLevel(logging.INFO)
APP.logger.addHandler(STDERR_LOG)

LOG = APP.logger


if APP.config.get('MM_AUTHENTICATION') == 'fas':
    # Use FAS for authentication
    try:
        from flask.ext.fas_openid import FAS
        FAS = FAS(APP)
    except ImportError:
        APP.logger.exception("Couldn't import flask-fas-openid")


import mirrormanager2
import mirrormanager2.lib as mmlib
import mirrormanager2.forms as forms
import mirrormanager2.login_forms as login_forms
import mirrormanager2.lib.model as model


SESSION = mmlib.create_session(APP.config['DB_URL'])


def is_mirrormanager_admin(user):
    """ Is the user a mirrormanager admin.
    """
    if not user:
        return False
    auth_method = APP.config.get('MM_AUTHENTICATION', None)

    if auth_method == 'fas':
        if not user.cla_done or len(user.groups) < 1:
            return False

    if auth_method in ('fas', 'local'):
        admins = APP.config['ADMIN_GROUP']
        if isinstance(admins, basestring):
            admins = [admins]
        admins = set(admins)

        return len(admins.intersection(set(user.groups))) > 0
    else:
        return user in APP.config['ADMIN_GROUP']


def is_site_admin(user, site):
    """ Is the user an admin of this site.
    """
    if not user:
        return False

    admins = [admin.username for admin in mirror.admins]

    return user.username in admins


def is_authenticated():
    """ Returns whether the user is currently authenticated or not. """
    return hasattr(flask.g, 'fas_user') and flask.g.fas_user is not None


def login_required(function):
    """ Flask decorator to ensure that the user is logged in. """
    @wraps(function)
    def decorated_function(*args, **kwargs):
        ''' Wrapped function actually checking if the user is logged in.
        '''
        if not is_authenticated():
            return flask.redirect(flask.url_for(
                'auth_login', next=flask.request.url))
        return function(*args, **kwargs)
    return decorated_function


def admin_required(function):
    """ Flask decorator to ensure that the user is logged in. """
    @wraps(function)
    def decorated_function(*args, **kwargs):
        ''' Wrapped function actually checking if the user is logged in.
        '''
        if not is_authenticated():
            return flask.redirect(flask.url_for(
                'auth_login', next=flask.request.url))
        elif not is_mirrormanager_admin(flask.g.fas_user):
            flask.flash('You are not an admin', 'error')
            return flask.redirect(flask.url_for('index'))
        return function(*args, **kwargs)
    return decorated_function


# # Flask application

@APP.context_processor
def inject_variables():
    """ Inject some variables into every template.
    """
    admin = False
    if hasattr(flask.g, 'fas_user') and flask.g.fas_user:
        admin = is_mirrormanager_admin(flask.g.fas_user)

    return dict(
        is_admin=admin,
        version=__version__
    )


@APP.route('/')
def index():
    """ Displays the index page.
    """
    products = mmlib.get_products(SESSION)
    arches = mmlib.get_arches(SESSION)
    arches_name = [arch.name for arch in arches]

    return flask.render_template(
        'index.html',
        products=products,
        arches=arches_name,
    )


@APP.route('/mirrors')
@APP.route('/mirrors/<p_name>/<p_version>')
@APP.route('/mirrors/<p_name>/<p_version>/<p_arch>')
def list_mirrors(p_name=None, p_version=None, p_arch=None):
    """ Displays the page listing all mirrors.
    """
    version_id = None
    arch_id = None
    if p_name and p_version:
        version = mmlib.get_version_by_name_version(
            SESSION, p_name, p_version)
        if version:
            version_id = version.id

    if p_arch:
        arch = mmlib.get_arch_by_name(SESSION, p_arch)
        if arch:
            arch_id = arch.id

    mirrors = mmlib.get_mirrors(
        SESSION,
        private=False,
        site_private=False,
        admin_active=True,
        user_active=True,
        site_admin_active=True,
        site_user_active=True,
        # last_checked_in=True,
        # last_crawled=True,
        up2date=True,
        host_category_url_private=False,
        version_id=version_id,
        arch_id=arch_id,
    )

    return flask.render_template(
        'mirrors.html',
        mirrors=mirrors,
    )


@APP.route('/site/mine')
@login_required
def mysite():
    """ Return the list of site managed by the user. """
    sites = mirrormanager2.lib.get_user_sites(
        SESSION, flask.g.fas_user.username)
    return flask.render_template(
        'my_sites.html',
        tag='mysites',
        username="%s's" % flask.g.fas_user.username,
        sites=sites,
    )


@APP.route('/admin/all_sites')
@admin_required
def all_sites():
    """ Return the list of all sites for the admins. """
    sites = mirrormanager2.lib.get_all_sites(SESSION)
    return flask.render_template(
        'my_sites.html',
        tag='allsites',
        username='Admin - List all',
        sites=sites,
    )


@APP.route('/site/new', methods=['GET', 'POST'])
@login_required
def site_new():
    """ Create a new site.
    """
    form = forms.AddSiteForm()
    if form.validate_on_submit():
        site = model.Site()
        SESSION.add(site)
        form.populate_obj(obj=site)
        site.created_by = flask.g.fas_user.username

        try:
            SESSION.flush()
            flask.flash('Site added')
        except SQLAlchemyError as err:  # pragma: no cover
            # We cannot check this as there is no unique constraint in the
            # Site table. So the only situation where it could fail is a
            # failure at the DB server level itself.
            SESSION.rollback()
            flask.flash('Could not create the new site')
            APP.logger.debug('Could not create the new site')
            APP.logger.exception(err)
            return flask.redirect(flask.url_for('index'))

        try:
            msg = mmlib.add_admin_to_site(
                SESSION, site, flask.g.fas_user.username)
            flask.flash(msg)
        except SQLAlchemyError as err:  # pragma: no cover
            # We cannot check this because the code check before adding the
            # new SiteAdmin and therefore the only situation where it could
            # fail is a failure at the DB server level itself.
            SESSION.rollback()
            APP.logger.debug(
                'Could not add admin "%s" to site "%s"' % (
                    flask.g.fas_user.username, site))
            APP.logger.exception(err)

        SESSION.commit()
        return flask.redirect(flask.url_for('index'))

    return flask.render_template(
        'site_new.html',
        form=form,
    )


@APP.route('/site/<int:site_id>', methods=['GET', 'POST'])
@login_required
def site_view(site_id):
    """ View information about a given site.
    """
    siteobj = mmlib.get_site(SESSION, site_id)

    if siteobj is None:
        flask.abort(404, 'Site not found')

    form = forms.AddSiteForm(obj=siteobj)
    if form.validate_on_submit():
        obj = form.populate_obj(obj=siteobj)

        try:
            SESSION.flush()
            flask.flash('Site Updated')
        except SQLAlchemyError as err:  # pragma: no cover
            # We cannot check this because the code check before adding the
            # new SiteAdmin and therefore the only situation where it could
            # fail is a failure at the DB server level itself.
            SESSION.rollback()
            flask.flash('Could not update the Site')
            APP.logger.debug('Could not update the Site')
            APP.logger.exception(err)

        SESSION.commit()
        return flask.redirect(flask.url_for('index'))

    return flask.render_template(
        'site.html',
        site=siteobj,
        form=form,
    )


@APP.route('/host/<int:site_id>/new', methods=['GET', 'POST'])
@login_required
def host_new(site_id):
    """ Create a new host.
    """
    siteobj = mmlib.get_site(SESSION, site_id)

    if siteobj is None:
        flask.abort(404, 'Site not found')

    form = forms.AddHostForm()
    if form.validate_on_submit():
        host = model.Host()
        SESSION.add(host)
        host.site_id = siteobj.id
        form.populate_obj(obj=host)
        host.bandwidth_int = int(host.bandwidth_int)
        host.asn = None if not host.asn else int(host.asn)

        try:
            SESSION.flush()
            flask.flash('Host added')
        except SQLAlchemyError as err:
            SESSION.rollback()
            flask.flash('Could not create the new host')
            APP.logger.debug('Could not create the new host')
            APP.logger.exception(err)

        SESSION.commit()
        return flask.redirect(flask.url_for('site_view', site_id=site_id))

    return flask.render_template(
        'host_new.html',
        form=form,
        site=siteobj,
    )


@APP.route('/site/<int:site_id>/admin/new', methods=['GET', 'POST'])
@login_required
def siteadmin_new(site_id):
    """ Create a new site_admin.
    """
    siteobj = mmlib.get_site(SESSION, site_id)

    if siteobj is None:
        flask.abort(404, 'Site not found')

    form = login_forms.LostPasswordForm()
    if form.validate_on_submit():
        site_admin = model.SiteAdmin()
        SESSION.add(site_admin)
        site_admin.site_id = siteobj.id
        form.populate_obj(obj=site_admin)

        try:
            SESSION.flush()
            flask.flash('Site Admin added')
        except SQLAlchemyError as err:  # pragma: no cover
            # We cannot check this as there is no unique constraint in the
            # Site table. So the only situation where it could fail is a
            # failure at the DB server level itself.
            SESSION.rollback()
            flask.flash('Could not add Site Admin')
            APP.logger.debug('Could not add Site Admin')
            APP.logger.exception(err)

        SESSION.commit()
        return flask.redirect(flask.url_for('site_view', site_id=site_id))

    return flask.render_template(
        'site_admin_new.html',
        form=form,
        site=siteobj,
    )


@APP.route('/site/<int:site_id>/admin/<int:admin_id>/delete', methods=['POST'])
@login_required
def siteadmin_delete(site_id, admin_id):
    """ Delete a site_admin.
    """
    form = forms.ConfirmationForm()
    if form.validate_on_submit():

        siteobj = mmlib.get_site(SESSION, site_id)

        if siteobj is None:
            flask.abort(404, 'Site not found')

        siteadminobj = mmlib.get_siteadmin(SESSION, admin_id)

        if siteadminobj is None:
            flask.abort(404, 'Site Admin not found')

        if siteadminobj not in siteobj.admins:
            flask.abort(404, 'Site Admin not related to this Site')

        if len(siteobj.admins) <= 1:
            flask.flash(
                'There is only one admin set, you cannot delete it.', 'error')
            return flask.redirect(flask.url_for('site_view', site_id=site_id))

        SESSION.delete(siteadminobj)

        try:
            SESSION.commit()
            flask.flash('Site Admin deleted')
        except SQLAlchemyError as err:  # pragma: no cover
            # We check everything before deleting so the only error we could
            # run in is DB server related, and that we can't fake in our
            # tests
            SESSION.rollback()
            flask.flash('Could not delete Site Admin', 'error')
            APP.logger.debug('Could not delete Site Admin')
            APP.logger.exception(err)

    return flask.redirect(flask.url_for('site_view', site_id=site_id))


@APP.route('/host/<host_id>', methods=['GET', 'POST'])
@login_required
def host_view(host_id):
    """ Create a new host.
    """
    hostobj = mmlib.get_host(SESSION, host_id)

    if hostobj is None:
        flask.abort(404, 'Host not found')

    form = forms.AddHostForm(obj=hostobj)
    if form.validate_on_submit():
        form.populate_obj(obj=hostobj)
        hostobj.bandwidth_int = int(hostobj.bandwidth_int)
        hostobj.asn = None if not hostobj.asn else int(hostobj.asn)

        try:
            SESSION.flush()
            flask.flash('Host updated')
        except SQLAlchemyError as err:  # pragma: no cover
            # We cannot check this because the code updates data therefore
            # the only situation where it could fail is a failure at the
            # DB server level itself.
            SESSION.rollback()
            flask.flash('Could not update the host')
            APP.logger.debug('Could not update the host')
            APP.logger.exception(err)

        SESSION.commit()
        return flask.redirect(flask.url_for('host_view', host_id=host_id))

    return flask.render_template(
        'host.html',
        form=form,
        host=hostobj,
    )


@APP.route('/host/<host_id>/host_acl_ip/new', methods=['GET', 'POST'])
@login_required
def host_acl_ip_new(host_id):
    """ Create a new host_acl_ip.
    """
    hostobj = mmlib.get_host(SESSION, host_id)

    if hostobj is None:
        flask.abort(404, 'Host not found')

    form = forms.AddHostAclIpForm()
    if form.validate_on_submit():
        host_acl = model.HostAclIp()
        SESSION.add(host_acl)
        host_acl.host_id = hostobj.id
        form.populate_obj(obj=host_acl)

        try:
            SESSION.flush()
            flask.flash('Host ACL IP added')
        except SQLAlchemyError as err:
            SESSION.rollback()
            flask.flash('Could not add ACL IP to the host')
            APP.logger.debug('Could not add ACL IP to the host')
            APP.logger.exception(err)

        SESSION.commit()
        return flask.redirect(flask.url_for('host_view', host_id=host_id))

    return flask.render_template(
        'host_acl_ip_new.html',
        form=form,
        host=hostobj,
    )


@APP.route('/host/<host_id>/host_acl_ip/<host_acl_ip_id>/delete',
           methods=['POST'])
@login_required
def host_acl_ip_delete(host_id, host_acl_ip_id):
    """ Delete a host_acl_ip.
    """
    form = forms.ConfirmationForm()
    if form.validate_on_submit():
        hostobj = mmlib.get_host(SESSION, host_id)

        if hostobj is None:
            flask.abort(404, 'Host not found')

        hostaclobj = mmlib.get_host_acl_ip(SESSION, host_acl_ip_id)

        if hostaclobj is None:
            flask.abort(404, 'Host ACL IP not found')
        else:
            SESSION.delete(hostaclobj)
        try:
            SESSION.flush()
            flask.flash('Host ACL IP deleted')
        except SQLAlchemyError as err:  # pragma: no cover
            # We check everything before deleting so the only error we could
            # run in is DB server related, and that we can't fake in our
            # tests
            SESSION.rollback()
            flask.flash('Could not add ACL IP to the host')
            APP.logger.debug('Could not add ACL IP to the host')
            APP.logger.exception(err)

        SESSION.commit()
    return flask.redirect(flask.url_for('host_view', host_id=host_id))


@APP.route('/host/<host_id>/netblock/new', methods=['GET', 'POST'])
@login_required
def host_netblock_new(host_id):
    """ Create a new host_netblock.
    """
    hostobj = mmlib.get_host(SESSION, host_id)

    if hostobj is None:
        flask.abort(404, 'Host not found')

    form = forms.AddHostNetblockForm()
    if form.validate_on_submit():
        host_netblock = model.HostNetblock()
        SESSION.add(host_netblock)
        host_netblock.host_id = hostobj.id
        form.populate_obj(obj=host_netblock)

        try:
            SESSION.flush()
            flask.flash('Host netblock added')
        except SQLAlchemyError as err:  # pragma: no cover
            # We cannot check this as there is no unique constraint in the
            # table. So the only situation where it could fail is a failure
            # at the DB server level itself.
            SESSION.rollback()
            flask.flash('Could not add netblock to the host')
            APP.logger.debug('Could not add netblock to the host')
            APP.logger.exception(err)

        SESSION.commit()
        return flask.redirect(flask.url_for('host_view', host_id=host_id))

    return flask.render_template(
        'host_netblock_new.html',
        form=form,
        host=hostobj,
    )


@APP.route('/host/<host_id>/host_netblock/<host_netblock_id>/delete',
           methods=['POST'])
@login_required
def host_netblock_delete(host_id, host_netblock_id):
    """ Delete a host_netblock.
    """
    form = forms.ConfirmationForm()
    if form.validate_on_submit():
        hostobj = mmlib.get_host(SESSION, host_id)

        if hostobj is None:
            flask.abort(404, 'Host not found')

        hostnetbobj = mmlib.get_host_netblock(SESSION, host_netblock_id)

        if hostnetbobj is None:
            flask.abort(404, 'Host netblock not found')
        else:
            SESSION.delete(hostnetbobj)
        try:
            SESSION.commit()
            flask.flash('Host netblock deleted')
        except SQLAlchemyError as err:  # pragma: no cover
            # We check everything before deleting so the only error we could
            # run in is DB server related, and that we can't fake in our
            # tests
            SESSION.rollback()
            flask.flash('Could not delete netblock of the host')
            APP.logger.debug('Could not delete netblock of the host')
            APP.logger.exception(err)

    return flask.redirect(flask.url_for('host_view', host_id=host_id))


@APP.route('/host/<host_id>/asn/new', methods=['GET', 'POST'])
@login_required
def host_asn_new(host_id):
    """ Create a new host_peer_asn.
    """
    hostobj = mmlib.get_host(SESSION, host_id)

    if hostobj is None:
        flask.abort(404, 'Host not found')

    form = forms.AddHostAsnForm()
    if form.validate_on_submit():
        host_asn = model.HostPeerAsn()
        SESSION.add(host_asn)
        host_asn.host_id = hostobj.id
        form.populate_obj(obj=host_asn)
        host_asn.asn = int(host_asn.asn)

        try:
            SESSION.flush()
            flask.flash('Host Peer ASN added')
        except SQLAlchemyError as err:  # pragma: no cover
            # We cannot check this as there is no unique constraint in the
            # table. So the only situation where it could fail is a failure
            # at the DB server level itself.
            SESSION.rollback()
            flask.flash('Could not add Peer ASN to the host')
            APP.logger.debug('Could not add Peer ASN to the host')
            APP.logger.exception(err)

        SESSION.commit()
        return flask.redirect(flask.url_for('host_view', host_id=host_id))

    return flask.render_template(
        'host_asn_new.html',
        form=form,
        host=hostobj,
    )


@APP.route('/host/<host_id>/host_asn/<host_asn_id>/delete',
           methods=['POST'])
@login_required
def host_asn_delete(host_id, host_asn_id):
    """ Delete a host_peer_asn.
    """
    form = forms.ConfirmationForm()
    if form.validate_on_submit():
        hostobj = mmlib.get_host(SESSION, host_id)

        if hostobj is None:
            flask.abort(404, 'Host not found')

        hostasnobj = mmlib.get_host_peer_asn(SESSION, host_asn_id)

        if hostasnobj is None:
            flask.abort(404, 'Host Peer ASN not found')
        else:
            SESSION.delete(hostasnobj)

        try:
            SESSION.commit()
            flask.flash('Host Peer ASN deleted')
        except SQLAlchemyError as err:  # pragma: no cover
            # We check everything before deleting so the only error we could
            # run in is DB server related, and that we can't fake in our
            # tests
            SESSION.rollback()
            flask.flash('Could not delete Peer ASN of the host')
            APP.logger.debug('Could not delete Peer ASN of the host')
            APP.logger.exception(err)

    return flask.redirect(flask.url_for('host_view', host_id=host_id))


@APP.route('/host/<host_id>/country/new', methods=['GET', 'POST'])
@login_required
def host_country_new(host_id):
    """ Create a new host_country.
    """
    hostobj = mmlib.get_host(SESSION, host_id)

    if hostobj is None:
        flask.abort(404, 'Host not found')

    form = forms.AddHostCountryForm()
    if form.validate_on_submit():
        country_name = form.country.data
        country = mmlib.get_country_by_name(SESSION, country_name)
        if country is None:
            flask.flash('Invalid country code')
            return flask.render_template(
                'host_country_new.html',
                form=form,
                host=hostobj,
            )

        host_country = model.HostCountry()
        host_country.host_id = hostobj.id
        host_country.country_id = country.id
        SESSION.add(host_country)

        try:
            SESSION.flush()
            flask.flash('Host Country added')
        except SQLAlchemyError as err:  # pragma: no cover
            # We cannot check this as there is no unique constraint in the
            # table. So the only situation where it could fail is a failure
            # at the DB server level itself.
            SESSION.rollback()
            flask.flash('Could not add Country to the host')
            APP.logger.debug('Could not add Country to the host')
            APP.logger.exception(err)

        SESSION.commit()
        return flask.redirect(flask.url_for('host_view', host_id=host_id))

    return flask.render_template(
        'host_country_new.html',
        form=form,
        host=hostobj,
    )


@APP.route('/host/<host_id>/host_country/<host_country_id>/delete',
           methods=['POST'])
@login_required
def host_country_delete(host_id, host_country_id):
    """ Delete a host_country.
    """
    form = forms.ConfirmationForm()
    if form.validate_on_submit():
        hostobj = mmlib.get_host(SESSION, host_id)

        if hostobj is None:
            flask.abort(404, 'Host not found')

        hostcntobj = mmlib.get_host_country(SESSION, host_country_id)

        if hostcntobj is None:
            flask.abort(404, 'Host Country not found')
        else:
            SESSION.delete(hostcntobj)

        try:
            SESSION.commit()
            flask.flash('Host Country deleted')
        except SQLAlchemyError as err:  # pragma: no cover
            # We check everything before deleting so the only error we could
            # run in is DB server related, and that we can't fake in our
            # tests
            SESSION.rollback()
            flask.flash('Could not delete Country of the host')
            APP.logger.debug('Could not delete Country of the host')
            APP.logger.exception(err)

    return flask.redirect(flask.url_for('host_view', host_id=host_id))


@APP.route('/host/<host_id>/category/new', methods=['GET', 'POST'])
@login_required
def host_category_new(host_id):
    """ Create a new host_category.
    """
    hostobj = mmlib.get_host(SESSION, host_id)

    if hostobj is None:
        flask.abort(404, 'Host not found')

    categories = mmlib.get_categories(SESSION)

    form = forms.AddHostCategoryForm(categories=categories)

    if flask.request.method == 'POST':
        try:
            form.category_id.data = int(form.category_id.data)
        except ValueError:
            pass

    if form.validate_on_submit():

        host_category = model.HostCategory()
        host_category.host_id = hostobj.id
        form.populate_obj(obj=host_category)
        host_category.category_id = int(host_category.category_id)
        SESSION.add(host_category)

        try:
            SESSION.commit()
            flask.flash('Host Category added')
            return flask.redirect(
                flask.url_for(
                    'host_category',
                    host_id=hostobj.id,
                    hc_id=host_category.id))
        except SQLAlchemyError as err:
            SESSION.rollback()
            flask.flash('Could not add Category to the host')
            APP.logger.debug('Could not add Category to the host')
            APP.logger.exception(err)

    return flask.render_template(
        'host_category_new.html',
        form=form,
        host=hostobj,
    )


@APP.route('/host/<host_id>/category/<hc_id>/delete', methods=['GET', 'POST'])
@login_required
def host_category_delete(host_id, hc_id):
    """ Delete a host_category.
    """
    form = forms.ConfirmationForm()
    if form.validate_on_submit():
        hostobj = mmlib.get_host(SESSION, host_id)

        if hostobj is None:
            flask.abort(404, 'Host not found')

        hcobj = mmlib.get_host_category(SESSION, hc_id)

        if hcobj is None:
            flask.abort(404, 'Host/Category not found')
        host_cat_ids = [cat.id for cat in hostobj.categories]

        if hcobj.id not in host_cat_ids:
            flask.abort(404, 'Category not associated with this host')
        else:
            for url in hcobj.urls:
                SESSION.delete(url)
            for dirs in hcobj.directories:
                SESSION.delete(dirs)
            SESSION.delete(hcobj)

        try:
            SESSION.commit()
            flask.flash('Host Category deleted')
        except SQLAlchemyError as err:  # pragma: no cover
            # We check everything before deleting so the only error we could
            # run in is DB server related, and that we can't fake in our
            # tests
            SESSION.rollback()
            flask.flash('Could not delete Category of the host')
            APP.logger.debug('Could not delete Category of the host')
            APP.logger.exception(err)

    return flask.redirect(flask.url_for('host_view', host_id=host_id))


@APP.route('/host/<host_id>/category/<hc_id>', methods=['GET', 'POST'])
@login_required
def host_category(host_id, hc_id):
    """ View a host_category.
    """
    hostobj = mmlib.get_host(SESSION, host_id)

    if hostobj is None:
        flask.abort(404, 'Host not found')

    hcobj = mmlib.get_host_category(SESSION, hc_id)

    if hcobj is None:
        flask.abort(404, 'Host/Category not found')

    host_cat_ids = [cat.id for cat in hostobj.categories]

    if hcobj.id not in host_cat_ids:
        flask.abort(404, 'Category not associated with this host')

    categories = mmlib.get_categories(SESSION)

    form = forms.EditHostCategoryForm(obj=hcobj)

    if form.validate_on_submit():

        form.populate_obj(obj=hcobj)

        try:
            SESSION.flush()
            flask.flash('Host Category updated')
        except SQLAlchemyError as err:  # pragma: no cover
            # We cannot check this because the code check before updating
            # and therefore the only situation where it could fail is a
            # failure at the DB server level itself.
            SESSION.rollback()
            flask.flash('Could not update Category to the host')
            APP.logger.debug('Could not update Category to the host')
            APP.logger.exception(err)

        SESSION.commit()
        return flask.redirect(
            flask.url_for('host_category', host_id=hostobj.id, hc_id=hcobj.id))

    return flask.render_template(
        'host_category.html',
        form=form,
        host=hostobj,
        hostcategory=hcobj,
    )


@APP.route('/host/<host_id>/category/<hc_id>/url/new', methods=['GET', 'POST'])
@login_required
def host_category_url_new(host_id, hc_id):
    """ Create a new host_category_url.
    """
    hostobj = mmlib.get_host(SESSION, host_id)

    if hostobj is None:
        flask.abort(404, 'Host not found')

    hcobj = mmlib.get_host_category(SESSION, hc_id)

    if hcobj is None:
        flask.abort(404, 'Host/Category not found')

    host_cat_ids = [cat.id for cat in hostobj.categories]

    if hcobj.id not in host_cat_ids:
        flask.abort(404, 'Category not associated with this host')

    categories = mmlib.get_categories(SESSION)

    form = forms.AddHostCategoryUrlForm()

    if form.validate_on_submit():

        host_category_u = model.HostCategoryUrl()
        host_category_u.host_category_id = hcobj.id
        form.populate_obj(obj=host_category_u)
        SESSION.add(host_category_u)

        try:
            SESSION.flush()
            flask.flash('Host Category URL added')
        except SQLAlchemyError as err:
            SESSION.rollback()
            flask.flash('Could not add Category URL to the host')
            APP.logger.debug('Could not add Category URL to the host')
            APP.logger.exception(err)

        SESSION.commit()
        return flask.redirect(
            flask.url_for('host_category', host_id=host_id, hc_id=hc_id))

    return flask.render_template(
        'host_category_url_new.html',
        form=form,
        host=hostobj,
        hostcategory=hcobj,
    )


@APP.route(
    '/host/<host_id>/category/<hc_id>/url/<host_category_url_id>/delete',
    methods=['POST'])
@login_required
def host_category_url_delete(host_id, hc_id, host_category_url_id):
    """ Delete a host_category_url.
    """
    form = forms.ConfirmationForm()
    if form.validate_on_submit():
        hostobj = mmlib.get_host(SESSION, host_id)

        if hostobj is None:
            flask.abort(404, 'Host not found')

        hcobj = mmlib.get_host_category(SESSION, hc_id)

        if hcobj is None:
            flask.abort(404, 'Host/Category not found')

        host_cat_ids = [cat.id for cat in hostobj.categories]

        if hcobj.id not in host_cat_ids:
            flask.abort(404, 'Category not associated with this host')

        hostcaturlobj = mmlib.get_host_category_url_by_id(
            SESSION, host_category_url_id)

        if hostcaturlobj is None:
            flask.abort(404, 'Host category URL not found')

        host_cat_url_ids = [url.id for url in hcobj.urls]

        if hostcaturlobj.id not in host_cat_url_ids:
            flask.abort(404, 'Category URL not associated with this host')
        else:
            SESSION.delete(hostcaturlobj)

        try:
            SESSION.commit()
            flask.flash('Host category URL deleted')
        except SQLAlchemyError as err:  # pragma: no cover
            # We check everything before deleting so the only error we could
            # run in is DB server related, and that we can't fake in our
            # tests
            SESSION.rollback()
            flask.flash('Could not delete category URL of the host')
            APP.logger.debug('Could not delete category URL of the host')
            APP.logger.exception(err)

    return flask.redirect(
        flask.url_for('host_category', host_id=host_id, hc_id=hc_id))


@APP.route('/login', methods=['GET', 'POST'])
def auth_login():  # pragma: no cover
    """ Login mechanism for this application.
    """
    next_url = flask.url_for('index')
    if 'next' in flask.request.values:
        next_url = flask.request.values['next']

    if next_url == flask.url_for('auth_login'):
        next_url = flask.url_for('index')

    if APP.config.get('MM_AUTHENTICATION', None) == 'fas':
        if hasattr(flask.g, 'fas_user') and flask.g.fas_user is not None:
            return flask.redirect(next_url)
        else:
            return FAS.login(
                return_url=next_url,
                groups=APP.config['ADMIN_GROUP'])
    elif APP.config.get('MM_AUTHENTICATION', None) == 'local':
        form = forms.LoginForm()
        return flask.render_template(
            'login.html',
            next_url=next_url,
            form=form,
        )


@APP.route('/logout')
def auth_logout():
    """ Log out if the user is logged in other do nothing.
    Return to the index page at the end.
    """
    next_url = flask.url_for('index')

    if APP.config.get('MM_AUTHENTICATION', None) == 'fas':
        if hasattr(flask.g, 'fas_user') and flask.g.fas_user is not None:
            FAS.logout()
            flask.flash("You are no longer logged-in")
    elif APP.config.get('MM_AUTHENTICATION', None) == 'local':
        login.logout()
    return flask.redirect(next_url)

import admin
import xmlrpc

# Only import the login controller if the app is set up for local login
if APP.config.get('MM_AUTHENTICATION', None) == 'local':
    import mirrormanager2.login
    APP.before_request(login._check_session_cookie)
    APP.after_request(login._send_session_cookie)
