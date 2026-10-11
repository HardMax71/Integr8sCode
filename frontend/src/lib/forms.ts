import { defaults, superForm, type FormOptions, type Infer, type SuperForm } from 'sveltekit-superforms';
import { zod4, type ZodValidationSchema } from 'sveltekit-superforms/adapters';
import * as z from 'zod/mini';
import { issueMessage } from '#lib/validation.ts';

/**
 * A form validated in the browser against a generated Zod schema, starting from the schema's defaults.
 * There's no form action, so `onUpdate` saves through a mutation once `form.valid` is true.
 * @param schema - A schema from `#lib/api/index.ts`, or one built from them
 * @param options - superForm options; `onUpdate` is the usual one
 * @param initial - Starting values over the defaults, such as the record being edited
 */
export function apiForm<S extends ZodValidationSchema>(
    schema: S,
    options: FormOptions<Infer<S, 'zod4'>> = {},
    initial?: Partial<Infer<S, 'zod4'>>,
): SuperForm<Infer<S, 'zod4'>> {
    const adapter = zod4(schema, { error: issueMessage });
    return superForm(initial ? defaults(initial, adapter) : defaults(adapter), {
        SPA: true,
        dataType: 'json',
        // No form action and no load function, so nothing to apply or rerun
        applyAction: false,
        invalidateAll: false,
        resetForm: false,
        validators: adapter,
        ...options,
    });
}

/** A text field the form won't send empty; the API's own rules for it still apply */
export function filled(schema: z.ZodMiniString): z.ZodMiniString {
    return schema.check(z.minLength(1));
}

/** A text field that may stay empty; anything typed must pass the API's rule */
export function optionalText(schema: z.ZodMiniString) {
    return z.union([z.literal(''), schema]);
}
