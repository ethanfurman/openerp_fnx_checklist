# -*- coding: utf-8 -*-

from aenum import NamedTuple
from collections import defaultdict
from fnx.oe import Normalize
from io import BytesIO
from openerp import pooler, SUPERUSER_ID
from openerp.exceptions import ERPError
from openerp.report.interface import report_int
from openerp.report.render import render
from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT
from osv import fields, osv
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
import logging


_logger = logging.getLogger(__name__)

# enumerations

class Status(fields.SelectionEnum):
    _order_ = 'ready active done'
    ready = 'Ready'
    active = 'In Progress'
    done = 'Done'

class Allowed_Response_Type(fields.SelectionEnum):
    _order_ = 'yes_no pass_fail done_skip'
    yes_no = 'Yes/No'
    pass_fail = 'Pass/Fail'
    done_skip = 'Done/Skip'

# models
##
## fnx.checklist
## fnx.checklist.question
## fnx.checklist.history
## fnx.checklist.history.answer


class checklist(Normalize, osv.AbstractModel):
    "checklist"
    _name = "fnx.checklist"
    _description = "checklist"
    #
    def __init__(self, pool, cr):
        super(checklist, self).__init__(pool, cr)
        # fix-up pointer fields
        self._columns['question_ids']._obj = '%s.question' % (self._name, )
        # register report
        checklist_report(self._name, 'report.%s.%s' % (self._module, self._name))
    #
    def _auto_init(self, cr, context=None):
        res = super(checklist, self)._auto_init(cr, context=context)
        # one-time creation of structures
        if self._name != 'fnx.checklist':
            add_report(self, cr, context)
        add_permissions(self, cr, context)
        return res
    #
    # extra columns added here should also be added to checklist.history
    #
    _columns = {
        'name': fields.char("Title", size=128, required=True),
        'description': fields.text('Description'),
        'question_ids': fields.one2many(
                "fnx.checklist.question", "checklist_id",
                string="Questions",
                ),
        }
    #
    _constraints = [
        (lambda s, *a: s.check_unique('name', *a), '\nChecklist name already exists', ['name']),
        ]


class question(Normalize, osv.AbstractModel):
    "checklist question"
    _name = "fnx.checklist.question"
    _description = "question"
    _rec_name = 'question'
    #
    def __init__(self, pool, cr):
        super(question, self).__init__(pool, cr)
        # fix-up pointer fields
        self._columns['checklist_id']._obj = self._name.rsplit('.', 1)[0]
    #
    def _auto_init(self, cr, context=None):
        res = super(question, self)._auto_init(cr, context=context)
        # one-time creation of structures
        add_permissions(self, cr, context)
        return res
    #
    _columns = {
        'question': fields.char("Question", size=128, required=True),
        'checklist_id': fields.many2one('fnx.checklist', 'Checklist', required=True),
        'response_type': fields.selection(
            Allowed_Response_Type,
            string='Allowed Responses',
            required=True,
            )
        }


class checklist_history(Normalize, osv.AbstractModel):
    "checklist history"
    _name = "fnx.checklist.history"
    _description = "checklist history"
    #
    def __init__(self, pool, cr):
        super(checklist_history, self).__init__(pool, cr)
        # fix-up pointer fields
        self._columns['checklist_id']._obj = self._name.rsplit('.', 1)[0]
        self._columns['answer_ids']._obj = '%s.answer' % (self._name, )
        user_id = self._columns['user_id']
        if self._name != 'fnx.checklist.history' and not user_id._domain:
            group_id = fields.ref('%s.group_%s_staff' % (self._module, self._module))
            user_id._domain = [('groups_id','=',group_id(pool, cr))]
        checklist_report(self._name, 'report.%s.%s' % (self._module, self._name))
    #
    def _auto_init(self, cr, context=None):
        res = super(checklist_history, self)._auto_init(cr, context=context)
        # one-time creation of structures
        if self._name != 'fnx.checklist.history':
            add_report(self, cr, context)
        add_permissions(self, cr, context)
        return res
    #
    _columns = {
        'name': fields.char("Name",size=128),
        'checklist_id': fields.many2one('fnx.checklist', 'Checklist'),
        'answer_ids': fields.one2many('fnx.checklist.history.answer', 'checklist_history_id', 'Responses'),
        'date_end': fields.datetime("Completed Date"),
        'user_id': fields.many2one(
            'res.users',
            'Assigned to',
            domain=[],
            ),
        'state': fields.selection(Status, "Status"),
        }
    #
    _defaults = {
        'state' : lambda *a: Status.ready,
        'user_id': lambda s, cr, uid, context: uid,
        }
    #
    def onchange_checklist_id(self, cr, uid, ids, id, context=None):
        question_model = '%s.question' % (self._name.rsplit('.', 1)[0])
        question_model = self.pool.get(question_model)
        question_ids = question_model.search(cr, uid, [('checklist_id', '=', id)], context=context)
        records = question_model.browse(cr, uid, question_ids, context=context)
        results = []
        for rec in records:
            obj = {'question': rec.question, 'response_type': rec.response_type}
            results.append(obj)
        return {'value': {'answer_ids': results}}


class question_history(Normalize, osv.AbstractModel):
    "checklist answer history"
    _name = "fnx.checklist.history.answer"
    _description = "answer"
    _rec_name = 'question'
    #
    def __init__(self, pool, cr):
        super(question_history, self).__init__(pool, cr)
        # fix-up pointer fields
        self._columns['checklist_history_id']._obj = self._name.rsplit('.', 1)[0]
    #
    def _auto_init(self, cr, context=None):
        res = super(question_history, self)._auto_init(cr, context=context)
        # one-time creation of structures
        add_permissions(self, cr, context)
        return res
    #
    _columns = {
        'question': fields.char("Question",size=128, required=True),
        'checklist_history_id': fields.many2one('fnx.checklist.history', 'Checklist'),
        'answer_id': fields.many2one('fnx.checklist.allowed_response', string="Response"),
        'detail': fields.char("Detail",size=128),
        'response_type': fields.selection(
            Allowed_Response_Type,
            string='Allowed Responses',
            required=True,
            ),
        }


class responses(osv.Model):
    "responses"
    _name = 'fnx.checklist.allowed_response'
    _description = 'response'
    _order = 'id'
    #
    _columns = {
        'name': fields.char('Name', size=7),
        'type': fields.char('Type', size=9),
        }

def add_permissions(model, cr, context):
    "add default permissions if none exist"
    cr.execute("SELECT id FROM ir_model WHERE model='%s'" % (model._name, ))
    model_id = cr.fetchone()[0]
    cr.execute("SELECT id FROM ir_model_access WHERE model_id=%s" % (model_id, ))
    #
    if not cr.rowcount:
        imd_name = 'access_%s_all' % (model._table, )
        ima_name = '%s_all' % (model._table, )
        #
        cr.execute("SELECT nextval('ir_model_access_id_seq')")
        ima_id = cr.fetchone()[0]
        cr.execute("""
                INSERT INTO ir_model_access
                    (
                      id, name, model_id, perm_read, perm_write, perm_create, perm_unlink,
                      create_uid, create_date, write_uid, write_date
                      )
                VALUES
                    (
                      %s, '%s', %s, true, true, true, true,
                      1, now() AT TIME ZONE 'UTC', 1, now() AT TIME ZONE 'UTC'
                      )
                    """
                    % (ima_id, ima_name, model_id)
                    )
        #
        cr.execute("SELECT nextval('ir_model_data_id_seq')")
        imd_id = cr.fetchone()[0]
        cr.execute("""
                INSERT into ir_model_data
                    (
                    id, module, name, model, res_id, date_init, date_update,
                    create_uid, create_date, write_uid, write_date,
                    noupdate
                    )
                VALUES
                    (
                      %s, '%s', '%s', 'ir.model.access', %s, now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC',
                      1, now() AT TIME ZONE 'UTC', 1, now() AT TIME ZONE 'UTC',
                      true
                      )
                    """
                    % (imd_id, model._module, imd_name, ima_id)
                    )

def add_report(model, cr, context):
    "add checklist report to model"
    #
    # calculate db values
    #
    module = model._module
    model_name = model._name
    title_name = model.__class__.__doc__.title().replace('.',' ')
    report_xml_id = '%s.%s' % (module, model_name)
    imd_xml_id = 'report_%s_%s' % (module, model._table)
    # ???_id will be calculated later
    #
    # get or create ir.actions.report.xml entry (ir_act_report_xml)
    # -------------------------------------------------------------------------------------------------------
    # |  id | header | model         | name         | report_name     | report_type | type                  |
    # | --- | ------ | ------------- | ------------ | --------------- | ----------- | --------------------- |
    # | ??? | t      | <model.name>  | <title name> | <report xml_id> | pdf         | ir.actions.report.xml |
    # -------------------------------------------------------------------------------------------------------
    #
    cr.execute("""
        SELECT id
        FROM ir_act_report_xml
        WHERE header='t' AND report_type='pdf' AND type='ir.actions.report.xml' AND
              model='%s' AND name='%s' AND report_name='%s'
              """
              % (model_name, title_name, report_xml_id)
              )
    rows = cr.fetchall()
    if len(rows) > 1:
        raise ValueError('%s: too many matches found:\n%s' % (model_name, rows))
    elif rows:
        action_id = rows[0][0]
    else:
        # create it
        cr.execute("SELECT nextval('ir_actions_id_seq')")
        action_id = cr.fetchone()[0]
        cr.execute("""
            INSERT INTO ir_act_report_xml
                (
                  id, header, report_type, type, model, name, report_name,
                  create_uid, create_date, write_uid, write_date,
                  auto, multi, attachment_use
                   )
            VALUES
                (
                  %s, 't', 'pdf', 'ir.actions.report.xml', '%s', '%s', '%s',
                  1, now() AT TIME ZONE 'UTC', 1, now() AT TIME ZONE 'UTC',
                  false, false, false
                  )
                """
                % (action_id, model_name, title_name, report_xml_id)
                  )
    #
    # get or create ir.model.data entry (ir_model_data)
    #
    # --------------------------------------------------------------------
    # | module           | name         | model                 | res_id |
    # | ---------------- | ------------ | --------------------- | ------ |
    # | <current module> | <imd xml_id> | ir.actions.report.xml | ???_id |
    # --------------------------------------------------------------------
    #
    cr.execute("""
        SELECT id, model, res_id
        FROM ir_model_data
        WHERE module='%s' AND name='%s'
        """
        % (module, imd_xml_id)
        )
    if not cr.rowcount:
        # create entry
        cr.execute("SELECT nextval('ir_model_data_id_seq')")
        imd_id = cr.fetchone()[0]
        cr.execute("""
            INSERT into ir_model_data
                (
                module, name, model, res_id, date_init, date_update,
                create_uid, create_date, write_uid, write_date,
                noupdate
                )
            VALUES
                (
                  '%s', '%s', '%s', %s, now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC',
                  1, now() AT TIME ZONE 'UTC', 1, now() AT TIME ZONE 'UTC',
                  true
                  )
                """
                % (module, imd_xml_id, model_name, action_id)
                )
    else:
        # validate entry
        imd_id, imd_model, imd_res_id = cr.fetchone()
        if imd_model != model_name or imd_res_id != action_id:
            raise ERPError(
                    'Duplicate Entry',
                    'record %s.%s already exists and points to %s:%s'
                        % (module, imd_xml_id, imd_model, imd_res_id),
                        )
    #
    # get or create ir.values entry (ir_values)
    #
    # --------------------------------------------------------------------------------------------
    # | key    | key2               | value                        | model        | name         |
    # | ------ | ------------------ | ---------------------------- | ------------ | ------------ |
    # | action | client_print_multi | ir.actions.report.xml,???_id | <model.name> | <title name> |
    # --------------------------------------------------------------------------------------------
    cr.execute("""
        SELECT id
        FROM ir_values
        WHERE
            key='action' AND
            key2='client_print_multi' AND
            value='ir.actions.report.xml,%s' AND
            model='%s'
            """
            % (action_id, model_name),
            )
    if not cr.rowcount:
        cr.execute("SELECT nextval('ir_values_id_seq')")
        iv_id = cr.fetchone()[0]
        cr.execute("""
            INSERT INTO ir_values
                (
                  id, key, key2, value, model, name, res_id,
                  create_uid, create_date, write_uid, write_date
                  )
            VALUES
                (
                  %s, 'action', 'client_print_multi', 'ir.actions.report.xml,%s', '%s', '%s', 0,
                  1, now() AT TIME ZONE 'UTC', 1, now() AT TIME ZONE 'UTC'
                  )
                """
                % (iv_id, action_id, model_name, title_name),
                )


class external_pdf(render):

    def __init__(self, pdf):
        render.__init__(self)
        self.pdf = pdf
        self.output_type='pdf'

    def _render(self):
        return self.pdf


class checklist_report(report_int):

    def __init__(self, model, *args, **kwds):
        self._model = model
        super(checklist_report, self).__init__(*args, **kwds)

    def create(self, cr, uid, ids, datas, context=None):
        if context is None:
            context = {}
        pool = pooler.get_pool(cr.dbname)
        # get lists
        checklist_ids = ids
        oe_checklist = pool.get(self._model)
        self.records = lists = oe_checklist.browse(
                cr, uid, checklist_ids,
                context=context,
                )
        self.count = len(lists)
        # get response types
        responses = defaultdict(list)
        for resp in pool.get('fnx.checklist.allowed_response').read(cr, SUPERUSER_ID, [('id','!=',0)], context=context):
            responses[resp['type']].append(resp['name'])
        # create canvas
        pdf_io = BytesIO()
        self.display = display = Canvas(pdf_io, pagesize=letter, bottomup=1)
        self.set_meta(lists)
        page = Area(*letter)
        # viewable_area = Area(page.width - 1.5*inch, page.height - 1.5*inch)
        left_margin = 0.75*inch
        bottom_margin = 1.0*inch
        right_margin = page.width - 0.75*inch
        top_margin = page.height - 0.75*inch
        self.margins = top_margin, right_margin, bottom_margin, left_margin
        top_left = Point(left_margin, top_margin)
        anchor = top_left
        for checklist in lists:
            anchor = self.set_header(checklist, anchor)
            left, top = anchor
            top -= 0.0625 * inch
            self.display.line(left, top, left+7.0*inch, top)
            top -= 0.5 * inch
            self.display.setFontSize(10)
            question_anchor = left, top
            if oe_checklist._name.endswith('.checklist'):
                for question in checklist.question_ids:
                    if top < bottom_margin:
                        left, top = question_anchor
                        self.display.showPage()
                        self.display.line(left, top+0.5*inch, left+7.0*inch, top+0.5*inch)
                        self.display.setFontSize(10)
                    choice = '%s  /  %s' % tuple(responses[question.response_type])[:2]
                    self.display.drawString(left, top, question.question)
                    self.display.drawRightString(left+7.0*inch, top, choice)
                    top -= 0.5 * inch
            elif oe_checklist._name.endswith('.checklist.history'):
                for question in checklist.answer_ids:
                    if top < bottom_margin:
                        self.showPage()
                        left, top = question_anchor
                    choice = question.answer_id.name
                    detail = question.detail
                    self.display.drawString(left, top, question.question)
                    self.display.drawRightString(left+7.0*inch, top, choice)
                    if detail:
                        self.display.drawString(left+0.25*inch, top-0.2*inch, 'add. info:  %s' % detail)
                    top -= 0.5 * inch
        display.showPage()
        display.save()
        self._filename = self.get_filename(lists)
        self.obj = external_pdf(pdf_io.getvalue())
        self.obj.render()
        return (self.obj.pdf, 'pdf')

    def get_filename(self, lists):
        return 'Checklist'

    def set_header(self, checklist, anchor):
        # display global checklist fields
        self.display.setFontSize(19)
        left, top = anchor
        # top -= 0.25*inch
        if 'checklist_id' in checklist:
            self.display.drawString(left, top, checklist.checklist_id.name)
            top -= 0.31*inch
            self.display.drawString(left, top, checklist.name)
        else:
            self.display.drawString(left, top, checklist.name)
            top -= 0.31*inch
        self.display.setFontSize(12)
        top -= 0.31*inch
        user = 'user_id' in checklist and checklist.user_id.name or ''
        self.display.drawString(left, top, 'Assigned to:  %s' % user)
        completed = 'Completed:  %s' % (
                'date_end' in checklist and
                checklist['date_end'] and
                checklist.date_end.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                or ''
                )
        self.display.drawString(left+4.5*inch, top, completed)
        return Point(left, top) # - 0.25*inch)

    def set_meta(self, lists):
        self.display.setAuthor('Sunridge Farms')
        self.display.setSubject('Product Specification Labels')
        if len(lists) == 1:
            self.display.setTitle('%s' % (lists[0].name, ))
        else:
            self.display.setTitle('Checklists')


class Area(NamedTuple):
    width = 0
    height = 1

class Point(NamedTuple):
    x = 0
    y = 1


# new module template
### -*- coding: utf-8 -*-
##
##from osv import osv
##import logging
##
##
##_logger = logging.getLogger(__name__)
##
### models
##
##class checklist(osv.Model):
##    "checklist"
##    _inherit = "fnx.checklist"
##    _name = "???.checklist"
##
##
##class question(osv.Model):
##    "checklist question"
##    _inherit = "fnx.checklist.question"
##    _name = "???.checklist.question"
##
##
##class checklist_history(osv.Model):
##    "checklist history"
##    _inherit = "fnx.checklist.history"
##    _name = "???.checklist.history"
##
##
##class question_history(osv.Model):
##    "checklist answer history"
##    _inherit = "fnx.checklist.history.answer"
##    _name = "???.checklist.history.answer"
##
