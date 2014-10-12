
// This program is free software; you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation; either version 2 of the License, or
// (at your option) any later version.

;(function () {

window.SystemQuickInfo = Backbone.View.extend({
    initialize: function () {
        this.render();
    },
    render: function () {
        this.$el.addClass('row-fluid');
        new SystemQuickDescription({model: this.model}).$el
            .addClass('span4').appendTo(this.$el);
        new SystemQuickHealth({model: this.model}).$el
            .addClass('span4').appendTo(this.$el);
        new SystemQuickUsage({model: this.model}).$el
            .addClass('span4').appendTo(this.$el);
    },
});

window.SystemQuickDescription = Backbone.View.extend({
    tagName: 'div',
    className: 'system-quick-description',
    template: JST['system-quick-description'],
    initialize: function () {
        this.listenTo(this.model, 'change', this.render);
        this.render();
    },
    render: function () {
        this.$el.html(this.template(this.model.attributes));
    },
});

window.SystemQuickHealth = Backbone.View.extend({
    tagName: 'div',
    className: 'system-quick-health',
    template: JST['system-quick-health'],
    events: {
        'click .report-problem': 'report_problem',
    },
    initialize: function () {
        this.listenTo(this.model, 'change', this.render);
        this.render();
    },
    render: function () {
        this.$el.html(this.template(this.model.attributes));
    },
    report_problem: function (evt) {
        new SystemReportProblemModal({model: this.model});
    },
});

window.SystemQuickUsage = Backbone.View.extend({
    tagName: 'div',
    className: 'system-quick-usage',
    template: JST['system-quick-usage'],
    events: {
        'click .take': 'take',
        'click .return': 'return',
        'click .borrow': 'borrow',
        'click .request-loan': 'request_loan',
        'click .return-loan': 'return_loan',
    },
    initialize: function () {
        this.request_in_progress = false;
        this.listenTo(this.model, 'change', this.render);
        this.render();
    },
    render: function () {
        this.$el.html(this.template(this.model.attributes));
    },
    success: function (model, xhr) {
        this.request_in_progress = false;
    },
    error: function (model, xhr) {
        this.request_in_progress = false;
        // XXX this isn't great... better to use notification float thingies
        this.$el.append(
            $('<div class="alert alert-error"/>')
            .text(xhr.statusText + ': ' + xhr.responseText));
    },
    take: function (evt) {
        evt.preventDefault();
        if (this.request_in_progress) return;
        this.request_in_progress = true;
        $(evt.currentTarget).addClass('disabled')
            .html('<i class="fa fa-spinner fa-spin"></i> Taking&hellip;');
        this.model.take({
            success: _.bind(this.success, this),
            error: _.bind(this.error, this),
        });
    },
    'return': function (evt) {
        evt.preventDefault();
        if (this.request_in_progress) return;
        this.request_in_progress = true;
        $(evt.currentTarget).addClass('disabled')
            .html('<i class="fa fa-spinner fa-spin"></i> Returning&hellip;');
        this.model.return({
            success: _.bind(this.success, this),
            error: _.bind(this.error, this),
        });
    },
    borrow: function (evt) {
        evt.preventDefault();
        if (this.request_in_progress) return;
        this.request_in_progress = true;
        $(evt.currentTarget).addClass('disabled')
            .html('<i class="fa fa-spinner fa-spin"></i> Borrowing&hellip;');
        this.model.borrow({
            success: _.bind(this.success, this),
            error: _.bind(this.error, this),
        });
    },
    request_loan: function (evt) {
        evt.preventDefault();
        if (this.request_in_progress) return;
        new SystemLoanRequestModal({model: this.model});
    },
    return_loan: function (evt) {
        evt.preventDefault();
        if (this.request_in_progress) return;
        this.request_in_progress = true;
        $(evt.currentTarget).addClass('disabled')
            .html('<i class="fa fa-spinner fa-spin"></i> Returning loan&hellip;');
        this.model.return_loan({
            success: _.bind(this.success, this),
            error: _.bind(this.error, this),
        });
    },
});

})();
