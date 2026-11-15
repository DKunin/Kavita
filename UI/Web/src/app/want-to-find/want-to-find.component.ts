import {ChangeDetectionStrategy, Component, inject, OnInit, signal, TrackByFunction} from '@angular/core';
import {translate, TranslocoDirective} from '@jsverse/transloco';
import {ToastrService} from '@openng/ngx-toastr';
import {NgbDropdown, NgbDropdownItem, NgbDropdownMenu, NgbDropdownToggle} from '@ng-bootstrap/ng-bootstrap';
import {WantToFindService} from '../_services/want-to-find.service';
import {WantToFind} from '../_models/want-to-find/want-to-find';
import {SideNavCompanionBarComponent} from '../sidenav/_components/side-nav-companion-bar/side-nav-companion-bar.component';
import {EmptyStateComponent} from '../shared/_components/empty-state/empty-state.component';
import {LoadingComponent} from '../shared/loading/loading.component';
import {ConfirmService} from '../shared/confirm.service';
import {ModalService} from '../_services/modal.service';
import {EditWantToFindModalComponent} from './_modals/edit-want-to-find-modal/edit-want-to-find-modal.component';
import {ResolveWantToFindModalComponent} from './_modals/resolve-want-to-find-modal/resolve-want-to-find-modal.component';
import {ModalResult} from '../_models/modal/modal-result';
import {AccountService} from '../_services/account.service';
import {CardDetailLayoutComponent} from '../cards/card-detail-layout/card-detail-layout.component';
import {ImageComponent} from '../shared/image/image.component';

@Component({
  selector: 'app-want-to-find',
  templateUrl: './want-to-find.component.html',
  styleUrl: './want-to-find.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslocoDirective, SideNavCompanionBarComponent, EmptyStateComponent, LoadingComponent,
    CardDetailLayoutComponent, ImageComponent, NgbDropdown, NgbDropdownToggle, NgbDropdownMenu, NgbDropdownItem
  ]
})
export class WantToFindComponent implements OnInit {
  private readonly service = inject(WantToFindService);
  private readonly confirmService = inject(ConfirmService);
  private readonly modalService = inject(ModalService);
  private readonly toastr = inject(ToastrService);
  private readonly accountService = inject(AccountService);

  items = signal<WantToFind[]>([]);
  isLoading = signal(true);
  isReadOnly = this.accountService.hasReadOnlyRole;
  trackByIdentity: TrackByFunction<WantToFind> = (_, item) => item.id;

  ngOnInit() {
    this.load();
  }

  load() {
    this.isLoading.set(true);
    this.service.getAll().subscribe(items => {
      this.items.set(items);
      this.isLoading.set(false);
    });
  }

  add() {
    this.openEditor(null);
  }

  edit(item: WantToFind) {
    this.openEditor(item);
  }

  openItem(item: WantToFind) {
    if (this.isReadOnly()) return;
    this.markFound(item);
  }

  markFound(item: WantToFind) {
    const ref = this.modalService.open(ResolveWantToFindModalComponent);
    ref.setInput('item', item);
    ref.closed.subscribe(() => {
      this.items.update(items => items.filter(i => i.id !== item.id));
      this.toastr.success(translate('want-to-find.resolved'));
    });
  }

  async delete(item: WantToFind) {
    if (!await this.confirmService.confirm(translate('want-to-find.delete-confirm', {title: item.title}))) return;
    this.service.delete(item.id).subscribe(() => {
      this.items.update(items => items.filter(i => i.id !== item.id));
      this.toastr.success(translate('want-to-find.deleted'));
    });
  }

  private openEditor(item: WantToFind | null) {
    const ref = this.modalService.open(EditWantToFindModalComponent, {size: 'lg'});
    ref.setInput('item', item);
    ref.closed.subscribe((result: ModalResult<WantToFind>) => {
      if (!result.data) return;
      this.load();
    });
  }
}
