using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using AutoMapper;
using AutoMapper.QueryableExtensions;
using Kavita.API.Repositories;
using Kavita.Models.DTOs.WantToFind;
using Kavita.Models.Entities.User;
using Microsoft.EntityFrameworkCore;

namespace Kavita.Database.Repositories;

public class WantToFindRepository(DataContext context, IMapper mapper) : IWantToFindRepository
{
    public void Add(AppUserWantToFind item) => context.AppUserWantToFind.Add(item);

    public void Update(AppUserWantToFind item) => context.Entry(item).State = EntityState.Modified;

    public void Remove(AppUserWantToFind item) => context.AppUserWantToFind.Remove(item);

    public Task<AppUserWantToFind?> GetAsync(int id, int userId, CancellationToken ct = default)
    {
        return context.AppUserWantToFind.FirstOrDefaultAsync(i => i.Id == id && i.AppUserId == userId, ct);
    }

    public async Task<IList<WantToFindDto>> GetDtosAsync(int userId, CancellationToken ct = default)
    {
        return await context.AppUserWantToFind
            .AsNoTracking()
            .Where(i => i.AppUserId == userId)
            .OrderBy(i => i.Title)
            .ProjectTo<WantToFindDto>(mapper.ConfigurationProvider)
            .ToListAsync(ct);
    }
}
