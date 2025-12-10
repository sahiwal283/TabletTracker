# Template Components

This directory contains reusable Jinja2 template fragments (macros and includes).

## Available Components

### Future Components

**`modals.html`** - Reusable modal macros
```jinja2
{% from "components/modals.html" import confirmation_modal %}
{{ confirmation_modal(id="delete-confirm", title="Confirm Delete") }}
```

**`forms.html`** - Form field macros
```jinja2
{% from "components/forms.html" import text_input, select_input %}
{{ text_input(name="email", label="Email", required=true) }}
```

**`tables.html`** - Table component macros
```jinja2
{% from "components/tables.html" import data_table %}
{{ data_table(data=submissions, columns=columns) }}
```

## Usage

Import components using Jinja2's `from` statement:

```jinja2
{% from "components/forms.html" import text_input %}
```

Or include entire component files:

```jinja2
{% include "components/modal_common.html" %}
```

## Note

Currently, modals and form elements are defined inline in individual templates or in `base.html`. These can be extracted into component macros as patterns emerge and duplication is identified.

