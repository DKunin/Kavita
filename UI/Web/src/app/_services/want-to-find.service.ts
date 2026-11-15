import {inject, Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {environment} from '../../environments/environment';
import {UpsertWantToFind, WantToFind} from '../_models/want-to-find/want-to-find';

@Injectable({providedIn: 'root'})
export class WantToFindService {
  private readonly httpClient = inject(HttpClient);
  private readonly baseUrl = environment.apiUrl + 'want-to-find';

  getAll() {
    return this.httpClient.get<WantToFind[]>(this.baseUrl);
  }

  create(item: UpsertWantToFind) {
    return this.httpClient.post<WantToFind>(this.baseUrl + '/create', item);
  }

  update(item: UpsertWantToFind) {
    return this.httpClient.post<WantToFind>(this.baseUrl + '/update', item);
  }

  delete(id: number) {
    return this.httpClient.delete<void>(this.baseUrl + '?wantToFindId=' + id);
  }

  resolve(wantToFindId: number, seriesId: number, addToWantToRead: boolean) {
    return this.httpClient.post<void>(this.baseUrl + '/resolve', {wantToFindId, seriesId, addToWantToRead});
  }
}
