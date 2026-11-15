import {ChangeDetectionStrategy, Component, inject, input, signal} from '@angular/core';
import {NgbActiveModal} from '@ng-bootstrap/ng-bootstrap';
import {FormField, form} from '@angular/forms/signals';
import {TranslocoDirective} from '@jsverse/transloco';
import {WantToFind} from '../../../_models/want-to-find/want-to-find';
import {WantToFindService} from '../../../_services/want-to-find.service';
import {TypeaheadConfigFactoryService} from '../../../typeahead-config-factory.service';
import {TypeaheadConfig} from '../../../typeahead/_models/typeahead-config';
import {SearchResult} from '../../../_models/search/search-result';
import {TypeaheadComponent} from '../../../typeahead/_components/typeahead.component';
import {modalSaved} from '../../../_models/modal/modal-result';

@Component({
  selector: 'app-resolve-want-to-find-modal',
  templateUrl: './resolve-want-to-find-modal.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, TypeaheadComponent, FormField]
})
export class ResolveWantToFindModalComponent {
  private readonly activeModal = inject(NgbActiveModal);
  private readonly service = inject(WantToFindService);
  private readonly typeaheadFactory = inject(TypeaheadConfigFactoryService);

  item = input.required<WantToFind>();
  selectedSeriesId = signal<number | null>(null);
  formModel = signal({addToWantToRead: true});
  formGroup = form(this.formModel);

  seriesConfig: TypeaheadConfig<SearchResult> = this.typeaheadFactory.forSearchResult({
    id: 'want-to-find-series',
    overrides: {minCharacters: 0}
  });

  updateSeries(results: SearchResult[]) {
    this.selectedSeriesId.set(results[0]?.seriesId ?? null);
  }

  close() {
    this.activeModal.dismiss();
  }

  resolve() {
    const seriesId = this.selectedSeriesId();
    if (seriesId === null) return;

    this.service.resolve(this.item().id, seriesId, this.formModel().addToWantToRead).subscribe(() => {
      this.activeModal.close(modalSaved(this.item()));
    });
  }
}
