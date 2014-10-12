
// This program is free software; you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation; either version 2 of the License, or
// (at your option) any later version.

;(function () {

window.SystemReportProblemModal = Backbone.View.extend({
    tagName: 'div',
    className: 'modal',
    template: JST['system-report-problem'],
    events: {
        'submit form': 'submit',
        'hidden': 'remove',
    },
    initialize: function () {
        this.render();
        this.$el.modal();
        this.$('[name=message]').focus();
    },
    render: function () {
        this.$el.html(this.template(this.model.attributes));
    },
    submit: function (evt) {
        evt.preventDefault();
        this.$('button').prop('disabled', true);
        this.$('button[type=submit]').html(
                '<i class="fa fa-spinner fa-spin"></i> Sending&hellip;');
        this.model.report_problem(
            this.$('[name=message]').val(),
            {success: _.bind(this.save_success, this),
             error: _.bind(this.save_error, this)});
    },
    save_success: function () {
        this.$el.modal('hide');
        $.bootstrapGrowl('<h4>Report sent</h4> Your problem report has been ' +
                'forwarded to the system owner.',
                {type: 'success'});
    },
    save_error: function (model, xhr) {
        this.$('.modal-footer').prepend(
            $('<div class="alert alert-error"/>')
            .text(xhr.statusText + ': ' + xhr.responseText));
    },
});

})();
