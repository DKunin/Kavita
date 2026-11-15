import {ChangeDetectionStrategy, Component, inject, input, OnInit, signal} from '@angular/core';
import {NgbActiveModal} from '@ng-bootstrap/ng-bootstrap';
import {form, FormField, maxLength, minLength, required} from '@angular/forms/signals';
import {translate, TranslocoDirective} from '@jsverse/transloco';
import {ToastrService} from '@openng/ngx-toastr';
import {WantToFind} from '../../../_models/want-to-find/want-to-find';
import {WantToFindService} from '../../../_services/want-to-find.service';
import {FormFieldDirective} from '../../../_directives/form-field.directive';
import {ValidationErrorsComponent} from '../../../shared/_components/validation-errors/validation-errors.component';
import {modalSaved} from '../../../_models/modal/modal-result';

@Component({
  selector: 'app-edit-want-to-find-modal',
  templateUrl: './edit-want-to-find-modal.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, FormField, FormFieldDirective, ValidationErrorsComponent]
})
export class EditWantToFindModalComponent implements OnInit {
  private readonly activeModal = inject(NgbActiveModal);
  private readonly service = inject(WantToFindService);
  private readonly toastr = inject(ToastrService);

  item = input<WantToFind | null>(null);

  formModel = signal({
    title: '',
    authors: '',
    summary: '',
    isbn: '',
    externalId: '',
    coverUrl: '',
    sourceUrl: '',
    notes: ''
  });

  formGroup = form(this.formModel, path => {
    required(path.title);
    minLength(path.title, 1);
    maxLength(path.title, 256);
    maxLength(path.authors, 1024);
    maxLength(path.isbn, 64);
    maxLength(path.externalId, 256);
    maxLength(path.coverUrl, 2048);
    maxLength(path.sourceUrl, 2048);
  });

  ngOnInit() {
    const item = this.item();
    if (!item) return;

    this.formModel.set({
      title: item.title,
      authors: item.authors,
      summary: item.summary ?? '',
      isbn: item.isbn ?? '',
      externalId: item.externalId ?? '',
      coverUrl: item.coverUrl ?? '',
      sourceUrl: item.sourceUrl ?? '',
      notes: item.notes ?? ''
    });
  }

  close() {
    this.activeModal.dismiss();
  }

  save() {
    if (this.formGroup().invalid()) return;

    const request = {...this.formModel(), id: this.item()?.id ?? 0};
    const operation = this.item() ? this.service.update(request) : this.service.create(request);
    operation.subscribe(saved => {
      this.toastr.success(translate(this.item() ? 'want-to-find.updated' : 'want-to-find.created'));
      this.activeModal.close(modalSaved(saved));
    });
  }
}
