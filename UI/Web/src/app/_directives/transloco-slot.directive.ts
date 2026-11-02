import {Directive, inject, input, TemplateRef} from '@angular/core';

@Directive({
  // eslint-disable-next-line @angular-eslint/directive-selector -- Existing public selector identifies projected translation slots.
  selector: 'ng-template[translocoSlot]',
  standalone: true,
})
export class TranslocoSlotDirective {
  readonly translocoSlot = input.required<string>();
  readonly tpl = inject(TemplateRef<unknown>);
}
