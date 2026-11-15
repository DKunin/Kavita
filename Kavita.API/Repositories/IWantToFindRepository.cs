#nullable enable
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Kavita.Models.DTOs.WantToFind;
using Kavita.Models.Entities.User;

namespace Kavita.API.Repositories;

public interface IWantToFindRepository
{
    void Add(AppUserWantToFind item);
    void Update(AppUserWantToFind item);
    void Remove(AppUserWantToFind item);
    Task<AppUserWantToFind?> GetAsync(int id, int userId, CancellationToken ct = default);
    Task<IList<WantToFindDto>> GetDtosAsync(int userId, CancellationToken ct = default);
}
